import os
import io
import re

from cs50 import SQL
from flask import Flask, url_for, session, jsonify
from flask import render_template, redirect, request
from flask import send_from_directory, send_file, flash
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZIP_DEFLATED
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash
from authlib.integrations.flask_client import OAuth

from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials

from helpers import login_required, create_drive, delete_file, delete_commit, delete_project

# Configure application
app = Flask(__name__)
app.secret_key = "!secret"
app.config.from_object("config")

# Ensure templates are auto-reloaded
app.config["TEMPLATES_AUTO_RELOAD"] = True


CONF_URL = "https://accounts.google.com/.well-known/openid-configuration"
oauth = OAuth(app)
oauth.register(
    name="google",
    server_metadata_url=CONF_URL,
    client_kwargs={
        "scope": "openid email profile"
    }
)


# Scopes required
SCOPES = ["openid",
          "https://www.googleapis.com/auth/userinfo.profile",
          "https://www.googleapis.com/auth/userinfo.email",
          "https://www.googleapis.com/auth/drive.file",
          "https://www.googleapis.com/auth/drive.appdata"]


# Configure CS50 Library to use SQLite database
db = SQL(os.getenv("DATABASE_URL"))


@app.route("/", methods=["GET", "POST"])
@login_required
def homepage():

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        # Get user id from session
        user = session.get("user")
        user_id = str(user["sub"])

        # Ensure dir is created
        temp = db.execute("SELECT dir FROM users WHERE id = ?", user_id)
        if not temp[0]["dir"]:
            # Create new project
            drive = create_drive()

            file_metadata = {
                "name": "OneProjectFile: Project Preview",
                "mimeType": "application/vnd.google-apps.folder"
            }

            file = drive.files().create(body=file_metadata,
                                        fields="id").execute()

            # Get project dir id from Drive
            dir_id = file.get("id")

            # Update dir in database
            db.execute("UPDATE users SET dir = ? WHERE id = ?", dir_id, user_id)
        else:
            dir_id = temp[0]["dir"]

        # Get project name
        name = request.form.get("name")

        # Ensure name is provided
        if not name:
            return "Error 403: Must provide name"

        # Determine currect date and time from SQL
        time = db.execute("SELECT now()")
        time = str(time[0]["now"])

        # Generate project id
        project_id = generate_password_hash(name.lower() + " " + time, method="pbkdf2:sha256", salt_length=8)

        # Create new project
        drive = create_drive()

        file_metadata = {
            "name": project_id,
            "parents": ["appDataFolder"],
            "mimeType": "application/vnd.google-apps.folder"
        }

        file = drive.files().create(body=file_metadata,
                                    fields="id").execute()

        # Get project search id from Drive
        project_search_id = file.get("id")

        # Add project to database
        db.execute("INSERT INTO projects (user_id, id, search_id, name, created, modified) VALUES (?, ?, ?, ?, ?, ?)",
                    user_id, project_id, project_search_id, name, time, time)

        # Save project name for dynamic routes
        project_name = name

        # Generate default branch master id
        name = "Master"
        branch_id = generate_password_hash(name.lower() + " " + time, method="pbkdf2:sha256", salt_length=8)

        # Create branch
        file_metadata = {
            "name": branch_id,
            "parents": [project_search_id],
            "mimeType": "application/vnd.google-apps.folder"
        }

        file = drive.files().create(body=file_metadata,
                                    fields="id").execute()

        # Get branch search id
        branch_search_id = file.get("id")

        # Add branch to database
        db.execute("INSERT INTO branches (project_id, id, search_id, name) VALUES (?, ?, ?, ?)",
                    project_id, branch_id, branch_search_id, name)

        # Update currect branch to database
        db.execute("UPDATE projects SET current_branch = ? WHERE id = ?", branch_id, project_id)

        # Get project preview
        preview = request.files["preview"]
        if preview:

            filename = secure_filename(preview.filename)
            if filename == "":
                return "Error 403: Must provide file name"

            file_ext = os.path.splitext(filename)[1]
            if file_ext not in [".png", ".jpg", ".jpeg"]:
                return "Error 403: Unsupported file format"

            temp_dir = TemporaryDirectory()

            preview.save(os.path.join(temp_dir.name, filename))

            file_metadata = {
                "name": project_name,
                "parents": [dir_id]
            }

            media = MediaFileUpload(os.path.join(temp_dir.name, filename),
                                    resumable=True)

            file = drive.files().create(body=file_metadata,
                                        media_body=media,
                                        fields="id").execute()

            # Get file search id
            project_preview = file.get("id")

            # Add project preview to database
            db.execute("UPDATE projects SET preview = ? WHERE id = ?", project_preview, project_id)

            temp_dir.cleanup()

        # Flash message
        flash(project_name + " sucessfully created!")

        return redirect(url_for(".project", project_name=secure_filename(project_name), project_id=project_id))

    # User reached route via GET (as by clicking a link or via redirect)
    else:

        # Get user id from session
        user = session.get("user")
        user_id = str(user["sub"])

        # Query database for projects
        projects = db.execute("SELECT * FROM projects WHERE user_id = ? ORDER BY modified DESC", user_id)

        if len(projects) == 0:
            return render_template("index.html")

        return render_template("index.html", projects=projects)


@app.route("/<project_name>/<project_id>")
@login_required
def project(project_name, project_id):


    # Get user id from session
    user = session.get("user")
    user_id = str(user["sub"])

    # Querry database for project
    project = db.execute("SELECT user_id, current_branch FROM projects WHERE id = ?", project_id)

    # Ensure user owns this project
    if str(project[0]["user_id"]) != str(user_id):
        return "Error 401: Unauthorized"

    # Querry database for branches
    branches = db.execute("SELECT id, name, current_commit FROM branches WHERE project_id = ?", project_id)

    # Get number of commits in each branch
    for branch in branches:
        count = db.execute("SELECT COUNT(id) FROM commits WHERE branch_id = ?", branch["id"])
        if len(count) == 1:
            branch["count"] = int(count[0]["count"])
        else:
            branch["count"] = 0

    # Get current branch name and id
    if len(branches) == 1:
        current_branch = branches[0]
    else:
        temp = db.execute("SELECT id, name, current_commit FROM branches WHERE id = ?", project[0]["current_branch"])
        current_branch = temp[0]

    # Querry database for commit history
    commits = db.execute("SELECT * FROM commits WHERE branch_id = ? ORDER BY created DESC", current_branch["id"])

    # Querry for project name and preview
    temp = db.execute("SELECT name, preview FROM projects WHERE id = ?", project_id)
    project_name = temp[0]["name"]
    project_preview = temp[0]["preview"]


    # Ensure commits exist
    if len(commits) == 0:
        return render_template("project.html", project_name=project_name, project_id=project_id,
                                current_branch=current_branch, branches=branches)

    # Get current commit id in current branch
    current_commit_id = current_branch["current_commit"]

    # Querry current commit details
    temp = db.execute("SELECT * FROM commits WHERE id = ?", current_commit_id)
    current_commit = temp[0]

    # Querry database for files from current_commit
    files = db.execute("SELECT id, name FROM files WHERE commit_id = ?", current_commit["id"])


    if project_preview:
        return render_template("project.html", project_name=project_name, project_id=project_id,
                                project_preview=project_preview, current_branch=current_branch,
                                current_commit=current_commit, branches=branches, commits=commits,
                                files=files)
    else:
        return render_template("project.html", project_name=project_name, project_id=project_id,
                                current_branch=current_branch, current_commit=current_commit,
                                branches=branches, commits=commits, files=files)


@app.route("/project_selector", methods=["POST"])
@login_required
def project_selector():

    project_name = request.form.get("name")
    project_id = request.form.get("id")

    # Error check
    if not project_name or not project_id:
        return "Error 400: Bad request"

    return redirect(url_for(".project", project_name=project_name, project_id=project_id))


@app.route("/branch_selector", methods=["POST"])
@login_required
def branch_selector():

    project_name = request.form.get("project_name")
    project_id = request.form.get("project_id")
    branch_id = request.form.get("branch_id")

    # Error check
    if not project_name or not project_id or not branch_id:
        return "Error 400: Bad request"

    # Get user id from session
    user = session.get("user")
    user_id = str(user["sub"])

    # Querry database for project
    project = db.execute("SELECT user_id, current_branch FROM projects WHERE id = ?", project_id)

    # Ensure user owns this project
    if str(project[0]["user_id"]) != str(user_id):
        return "Error 401: Unauthorized"

    # Validate branch id
    temp = db.execute("SELECT name FROM branches WHERE id = ?", branch_id)
    if len(temp) != 1:
        return "Error 404: Branch not found"

    # Update currect branch to database
    db.execute("UPDATE projects SET current_branch = ? WHERE id = ?", branch_id, project_id)

    return redirect(url_for(".project", project_name=project_name, project_id=project_id))


@app.route("/commit_selector", methods=["POST"])
@login_required
def commit_selector():

    project_name = request.form.get("project_name")
    project_id = request.form.get("project_id")
    current_branch_id = request.form.get("current_branch_id")
    commit_id = request.form.get("commit_id")

    # Error check
    if not project_name or not project_id or not current_branch_id or not commit_id:
        return "Error 400: Bad request"

    # Get user id from session
    user = session.get("user")
    user_id = str(user["sub"])

    # Querry database for project
    project = db.execute("SELECT user_id, current_branch FROM projects WHERE id = ?", project_id)

    # Ensure user owns this project
    if str(project[0]["user_id"]) != str(user_id):
        return "Error 401: Unauthorized"

    # Validate branch id
    temp = db.execute("SELECT name FROM branches WHERE id = ?", current_branch_id)
    if len(temp) != 1:
        return "Error 404: Branch not found"

    # Validate commit id
    temp = db.execute("SELECT created FROM commits WHERE id = ?", commit_id)
    if len(temp) != 1:
        return "Error 404: Commit not found"

    # Update currect commit to database
    db.execute("UPDATE branches SET current_commit = ? WHERE id = ?", commit_id, current_branch_id)

    return redirect(url_for(".project", project_name=project_name, project_id=project_id))


@app.route("/commit", methods=["POST"])
@login_required
def commit():

    project_name = request.form.get("project_name")
    project_id = request.form.get("project_id")
    current_branch_id = request.form.get("current_branch_id")

    # Error check
    if not project_name or not project_id or not current_branch_id:
        return "Error 400: Bad request"

    # Get user id from session
    user = session.get("user")
    user_id = str(user["sub"])

    # Querry database for project
    project = db.execute("SELECT user_id, current_branch FROM projects WHERE id = ?", project_id)

    # Ensure user owns this project
    if str(project[0]["user_id"]) != str(user_id):
        return "Error 401: Unauthorized"

    # Querry database for branch details
    branch = db.execute("SELECT * FROM branches WHERE id = ?", current_branch_id)

    # Validate branch id
    if len(branch) != 1:
        return "Error 404: Branch not found"

    # Validate project id
    if branch[0]["project_id"] != project_id:
        return "Error 403: Branch not not belong to project"

    # Get branch search id
    branch_search_id = branch[0]["search_id"]

    # Get current commit id in current branch
    current_commit_id = branch[0]["current_commit"]

    if current_commit_id:
        # Querry current commit details
        temp = db.execute("SELECT * FROM commits WHERE id = ?", current_commit_id)
        current_commit = temp[0]

        # Querry for latest commit
        temp = db.execute("SELECT id FROM commits WHERE branch_id = ? ORDER BY created DESC LIMIT 1", branch[0]["id"])
        latest_commit = temp[0]["id"]

        # Commiting to older version
        if current_commit["id"] != latest_commit:

            # Get created of current_commit
            temp = db.execute("SELECT created FROM commits WHERE id = ?", current_commit["id"])
            created = temp[0]["created"]

            # Get commits to be deleted
            commits = db.execute("SELECT id, search_id FROM commits WHERE created > ?", created)

            for commit in commits:
                delete_commit(commit["id"], commit["search_id"])

    # Create commit
    drive = create_drive()

    # Get commit message
    message = request.form.get("message")

    # Determine currect date and time from SQL
    time = db.execute("SELECT now()")
    time = str(time[0]["now"])

    # Generate commit id
    commit_id = generate_password_hash(message.lower() + " " + time, method="pbkdf2:sha256", salt_length=8)

    file_metadata = {
        "name": commit_id,
        "parents": [branch_search_id],
        "mimeType": "application/vnd.google-apps.folder"
    }

    file = drive.files().create(body=file_metadata,
                                fields="id").execute()

    # Get commit search id
    commit_search_id = file.get("id")

    # Get description
    description = request.form.get("description")
    if description:
        # Add commit to database
        db.execute("INSERT INTO commits (branch_id, id, search_id, message, description, created) VALUES (?, ?, ?, ?, ?, ?)",
                    current_branch_id, commit_id, commit_search_id, message, description, time)
    else:
        # Add commit to database
        db.execute("INSERT INTO commits (branch_id, id, search_id, message, created) VALUES (?, ?, ?, ?, ?)",
                    current_branch_id, commit_id, commit_search_id, message, time)

    # Upload files
    uploaded_files = request.files.getlist("files")

    for uploaded_file in uploaded_files:


        filename = secure_filename(uploaded_file.filename)
        if filename == "":
            return "Error 403: Must provide file name"

        file_ext = os.path.splitext(filename)[1]
        if file_ext in [".html", ".php", ".py"]:
            return "Error 403: Unsupported file format"


        temp_dir = TemporaryDirectory()

        uploaded_file.save(os.path.join(temp_dir.name, filename))

        # Generate file id
        file_id = generate_password_hash(filename.lower() + " " + time, method="pbkdf2:sha256", salt_length=8)

        file_metadata = {
            "name": file_id,
            "parents": [commit_search_id]
        }

        media = MediaFileUpload(os.path.join(temp_dir.name, filename),
                                resumable=True)

        file = drive.files().create(body=file_metadata,
                                    media_body=media,
                                    fields="id").execute()

        # Get file search id
        file_search_id = file.get("id")

        # Update file to database
        db.execute("INSERT INTO files (commit_id, id, search_id, name) VALUES (?, ?, ?, ?)",
                    commit_id, file_id, file_search_id, filename)

        temp_dir.cleanup()

    # Handel unmodified files
    if current_commit_id:
        # Query for files in current commit
        files = db.execute("SELECT name, id, search_id FROM files WHERE commit_id = ?", current_commit_id)

        files_modified = 0
        files_added = 0
        copy = files
        for uploaded_file in uploaded_files:
            modified = False
            filename = secure_filename(uploaded_file.filename)

            for file in files:
                search = file["name"].split(".")
                if re.search("^" + search[0] + "(_[0-9]+)?\." + search[1] , filename):
                    # Files modified
                    files_modified = files_modified + 1
                    modified = True

                    # Remove file from  copy
                    copy.remove(file)
                    break

            if not modified:
                # Files added
                files_added = files_added + 1

        # Copy unmodified files into new commit
        for file in copy:

            # Generate new file id
            file_id = generate_password_hash(file["name"].lower() + " " + time, method="pbkdf2:sha256", salt_length=8)

            db.execute("INSERT INTO files (commit_id, id, search_id, name) VALUES (?, ?, ?, ?)",
                        commit_id, file_id, file["search_id"], file["name"])


        if files_modified:
            num = files_modified
            if num > 1:
                modified = str(num) + " files modified."
            else:
                modified = str(num) + " file modified."
        if files_added:
            num = files_added
            if num > 1:
                added = str(num) + " files added."
            else:
                added = str(num) + " file added."
        if files_modified and files_added:
            flash(modified + " " + added)
        elif files_modified:
            flash(modified)
        elif files_added:
            flash(added)

    # Update currect commit to database
    db.execute("UPDATE branches SET current_commit = ? WHERE id = ?", commit_id, current_branch_id)

    # Update last modified to database
    db.execute("UPDATE projects SET modified = ? WHERE id = ?", time, project_id)



    return redirect(url_for(".project", project_name=project_name, project_id=project_id))


@app.route("/branch", methods=["POST"])
@login_required
def branch():

    project_name = request.form.get("project_name")
    project_id = request.form.get("project_id")

    # Error check
    if not project_name or not project_id:
        return "Error 400: Bad request"

    # Get user id from session
    user = session.get("user")
    user_id = str(user["sub"])

    # Querry database for project
    project = db.execute("SELECT user_id, search_id, current_branch FROM projects WHERE id = ?", project_id)

    # Ensure user owns this project
    if str(project[0]["user_id"]) != str(user_id):
        return "Error 401: Unauthorized"

    # Generate new branch
    drive = create_drive()

    # Get branch name
    name = request.form.get("name")

    # Determine currect date and time from SQL
    time = db.execute("SELECT now()")
    time = str(time[0]["now"])

    # Get project search id
    project_search_id = project[0]["search_id"]

    branch_id = generate_password_hash(name.lower() + " " + time, method="pbkdf2:sha256", salt_length=8)

    # Create branch
    file_metadata = {
        "name": branch_id,
        "parents": [project_search_id],
        "mimeType": "application/vnd.google-apps.folder"
    }

    file = drive.files().create(body=file_metadata,
                                fields="id").execute()

    # Get branch search id
    branch_search_id = file.get("id")

    # Add branch to database
    db.execute("INSERT INTO branches (project_id, id, search_id, name) VALUES (?, ?, ?, ?)",
                project_id, branch_id, branch_search_id, name)

    # Update currect branch to database
    db.execute("UPDATE projects SET current_branch = ? WHERE id = ?", branch_id, project_id)

    return redirect(url_for(".project", project_name=project_name, project_id=project_id))


@app.route("/login", methods=["GET", "POST"])
def login():

    # User reached route via POST (as by submitting a form via POST)
    if request.method == "POST":

        redirect_uri = url_for("auth", _external=True)
        return oauth.google.authorize_redirect(redirect_uri)

    # User reached route via GET (as by clicking a link or via redirect)
    else:
        return render_template("login.html")


@app.route("/auth")
def auth():
    token = oauth.google.authorize_access_token()
    user = oauth.google.parse_id_token(token)
    session["user"] = user
    session["token"] = token

    sub = str(user["sub"])
    row = db.execute("SELECT * FROM users WHERE id = ?", sub)


    # Authorize the user
    flow = Flow.from_client_config(client_config=app.config["CLIENT_CONFIG"], scopes=SCOPES)

    flow.redirect_uri = url_for("oauth2callback", _external=True)

    authorization_url, state = flow.authorization_url(
                access_type="offline",
                login_hint=sub,
                include_granted_scopes="true")

    # Store state in session
    session["state"] = state

    # Ensure user is logging in for the first time
    if len(row) == 0:
        # Add user to database
        db.execute("INSERT INTO users (id) VALUES (?)", sub)

    return redirect(authorization_url)


@app.route("/oauth2callback")
def oauth2callback():

    state = session["state"]

    flow = Flow.from_client_config(client_config=app.config["CLIENT_CONFIG"], scopes=SCOPES, state=state)
    flow.redirect_uri = url_for("oauth2callback")

    # Use the authorization server's response to fetch the OAuth 2.0 tokens.
    authorization_response = request.url
    flow.fetch_token(authorization_response=authorization_response)

    # Store credentials in the session.
    credentials = flow.credentials
    session["credentials"] = {"token": credentials.token,
                              "refresh_token": credentials.refresh_token,
                              "token_uri": credentials.token_uri,
                              "client_id": credentials.client_id,
                              "client_secret": credentials.client_secret,
                              "scopes": credentials.scopes}

    # Flash message
    flash("Hello, " + session["user"]["given_name"] + "!")

    return redirect("/")


@app.route("/clone/<file_id>")
@login_required
def clone(file_id):


    # Querry for file search id
    temp = db.execute("SELECT search_id, name FROM files WHERE id = ?", file_id)

    # Validate file id
    if len(temp) != 1:
        return "Error 404: File not found"

    file_search_id = temp[0]["search_id"]

    # Get name of file
    name = temp[0]["name"]

    drive = create_drive()

    request = drive.files().get_media(fileId=file_search_id)

    temp_dir = TemporaryDirectory()

    fh = io.FileIO(temp_dir.name + "/" + name, "wb")
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while done is False:
        status, done = downloader.next_chunk()
        print (int(status.progress() * 100))

    return send_from_directory(temp_dir.name + "/", name, as_attachment=True)


@app.route("/clone_commit", methods=["POST"])
@login_required
def clone_commit():

    # Get commit id
    commit_id = request.form.get("commit_id")

    project_name = request.form.get("project_name")

    # Validate commit id
    temp = db.execute("SELECT search_id FROM commits WHERE id = ?", commit_id)
    if len(temp) != 1:
        return "Error 404: Commit not found"

    # Querry for files in commit
    files = db.execute("SELECT search_id, name FROM files WHERE commit_id = ?", commit_id)

    drive = create_drive()

    temp_dir = TemporaryDirectory()

    # Download each file into a folder
    for file in files:

        name = file["name"]

        request_drive = drive.files().get_media(fileId=file["search_id"])

        fh = io.FileIO(temp_dir.name + "/" + name, "wb")
        downloader = MediaIoBaseDownload(fh, request_drive)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            print (int(status.progress() * 100))

    temp_zip = TemporaryDirectory()
    zipf = ZipFile(temp_zip.name + "/" + project_name + ".zip", "w", ZIP_DEFLATED)
    for root, dirs, files in os.walk(temp_dir.name):
        for file in files:
            zipf.write(temp_dir.name + "/" + file)
    zipf.close()
    return send_from_directory(temp_zip.name + "/", project_name + ".zip", as_attachment=True)


@app.route("/delete_file", methods=["POST"])
@login_required
def delete():

    # Get file id
    file_id = request.form.get("file_id")

    # Validate file id
    temp = db.execute("SELECT search_id FROM files WHERE id = ?", file_id)
    if len(temp) != 1:
        return "Error 400: Bad request"

    # Get file search id
    file_search_id = temp[0]["search_id"]

    # Get current commit id
    current_commit_id = request.form.get("current_commit_id")

    # Ensure user doesn't delete all files from commit
    temp = db.execute("SELECT id FROM files WHERE commit_id = ?", current_commit_id)
    if len(temp) == 1:
        return "Error 403: Can't delete all files from commit"

    delete_file(file_id, file_search_id)

    # Get project name and id
    project_id = request.form.get("project_id")
    project_name = request.form.get("project_name")

    return redirect(url_for(".project", project_name=project_name, project_id=project_id))


@app.route("/delete_commit", methods=["POST"])
@login_required
def delete_commit_route():

    commit_id = request.form.get("current_commit_id")

    # Validate current commit id
    temp = db.execute("SELECT search_id FROM commits WHERE id = ?", commit_id)
    if len(temp) != 1:
        return "Error 400: Bad request"

    commit_search_id = temp[0]["search_id"]

    # Delete commit
    delete_commit(commit_id, commit_search_id)

    # Get project name and id
    project_name = request.form.get("project_name")
    project_id = request.form.get("project_id")

    # Get current branch id
    temp = db.execute("SELECT current_branch FROM projects WHERE id = ?", project_id)
    current_branch_id = temp[0]["current_branch"]

    # Get latest commit id
    temp = db.execute("SELECT * FROM commits WHERE branch_id = ? ORDER BY created DESC LIMIT 1", current_branch_id)
    if len(temp) == 1:
        latest_commit = temp[0]["id"]
    else:
        latest_commit = None

    # Update current commit id to latest commit
    db.execute("UPDATE branches SET current_commit = ? WHERE project_id = ?", latest_commit, project_id)

    return redirect(url_for(".project", project_name=project_name, project_id=project_id))


@app.route("/delete_project", methods=["POST"])
@login_required
def delete_project_route():

    # Get project id
    project_id = request.form.get("project_id")

    # Get user id from session
    user = session.get("user")
    user_id = str(user["sub"])

    # Validate project id
    temp = db.execute("SELECT user_id, search_id FROM projects WHERE id = ?", project_id)
    if len(temp) != 1:
        return "Error 400: Bad request"

    # Ensure user owns project
    if temp[0]["user_id"] != user_id:
        return "Error 400: Bad request"

    # Get search id
    project_search_id = temp[0]["search_id"]

    delete_project(project_id, project_search_id)

    return redirect("/")


@app.route("/update_preview", methods=["POST"])
@login_required
def update_preview():

    # Get project name and id
    project_name = request.form.get("project_name")
    project_id = request.form.get("project_id")

    # Get user id from session
    user = session.get("user")
    user_id = str(user["sub"])

    # Ensure dir is created
    temp = db.execute("SELECT dir FROM users WHERE id = ?", user_id)
    if not temp:
        return "Error 400: Bad request"

    dir_id = temp[0]["dir"]

    drive = create_drive()

    # Get project preview
    uploaded_file = request.files.get("file")


    filename = secure_filename(uploaded_file.filename)
    if filename == "":
        return "Error 403: Must provide file name"

    file_ext = os.path.splitext(filename)[1]
    if file_ext in [".html", ".php", ".py"]:
        return "Error 403: Unsupported file format"


    temp_dir = TemporaryDirectory()

    uploaded_file.save(os.path.join(temp_dir.name, filename))

    file_metadata = {
        "name": project_name,
        "parents": [dir_id]
    }

    media = MediaFileUpload(os.path.join(temp_dir.name, filename),
                            resumable=True)

    file = drive.files().create(body=file_metadata,
                                media_body=media,
                                fields="id").execute()

    # Get file search id
    project_preview_id = file.get("id")

    temp_dir.cleanup()

    # Querry for preview
    temp = db.execute("SELECT preview FROM projects WHERE id = ?", project_id)
    if temp[0]["preview"]:
        # Delete from google drive
        drive.files().delete(fileId=temp[0]["preview"]).execute()

    # Update preview in database
    db.execute("UPDATE projects SET preview = ? WHERE id = ?", project_preview_id, project_id)

    return redirect(url_for(".project", project_name=project_name, project_id=project_id))


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# Error handeling - session expired
@app.errorhandler(500)
def internal_error(error):
    session.clear()
    flash("Session Timeout. Login to continue.")
    return redirect("/")
