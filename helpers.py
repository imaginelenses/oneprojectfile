import os

from cs50 import SQL
from flask import redirect, render_template, request, session
from functools import wraps

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

import google.auth.transport.requests
import requests


# Configure CS50 Library to use SQLite database
db = SQL(os.getenv("DATABASE_URL"))


def login_required(f):
    """
    Decorate routes to require login.

    http://flask.pocoo.org/docs/1.0/patterns/viewdecorators/
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):

        if session.get("user") is None or session.get("token") is None:
            return redirect("/login")

        return f(*args, **kwargs)
    return decorated_function


def create_drive():
    # Load credentials from the session.
    credentials = Credentials(token= session["credentials"]["token"],
                              refresh_token=session["credentials"]["refresh_token"],
                              token_uri=session["credentials"]["token_uri"],
                              client_id=session["credentials"]["client_id"],
                              client_secret=session["credentials"]["client_secret"],
                              scopes=session["credentials"]["scopes"])

    try:
        drive = build("drive", "v3", credentials=credentials)
    except:
        request = google.auth.transport.requests.Request()
        credentials.refresh(request)

    return drive


def refreshToken(client_id, client_secret, refresh_token):
    params = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token
    }

    authorization_url = "https://www.googleapis.com/oauth2/v4/token"

    r = requests.post(authorization_url, data=params)

    if r.ok:
            return r.json()['access_token']
    else:
            return None


def delete_file(file_id, file_search_id):

    drive = create_drive()

    # Delete from google drive
    drive.files().delete(fileId=file_search_id).execute()

    # Delete from database
    db.execute("DELETE FROM files WHERE id = ?", file_id)

    return


def delete_commit(commit_id, commit_search_id):

    drive = create_drive()

    # Delete from google drive
    drive.files().delete(fileId=commit_search_id).execute()

    # Delete files in commit from database
    db.execute("DELETE FROM files WHERE commit_id = ?", commit_id)

    # Delete commit from database
    db.execute("DELETE FROM commits WHERE id = ?", commit_id)

    return


def delete_project(project_id, project_search_id):

    drive = create_drive()

    # Delete from google drive
    drive.files().delete(fileId=project_search_id).execute()

    # Querry for branches in project
    branches = db.execute("SELECT id FROM branches WHERE project_id = ?", project_id)

    for branch in branches:

        # Querry for commits in branch
        commits = db.execute("SELECT id FROM commits WHERE branch_id = ?", branch["id"])

        # Delete all files in commit from database
        for commit in commits:
            db.execute("DELETE FROM files WHERE commit_id = ?", commit["id"])

        # Delete all commits in branch from database
        db.execute("DELETE FROM commits WHERE branch_id = ?", branch["id"])

    # Delete all branches in project from database
    db.execute("DELETE FROM branches WHERE project_id = ?", project_id)

    # Delete project from database
    db.execute("DELETE FROM projects WHERE id = ?", project_id)

    return

