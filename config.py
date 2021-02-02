import os

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
GOOGLE_REDIRECT_URIS = os.getenv("GOOGLE_REDIRECT_URIS")

CLIENT_CONFIG = {"web": {"client_id":GOOGLE_CLIENT_ID,
                         "project_id":"oneprojectfile",
                         "auth_uri":"https://accounts.google.com/o/oauth2/auth",
                         "token_uri":"https://oauth2.googleapis.com/token",
                         "auth_provider_x509_cert_url":"https://www.googleapis.com/oauth2/v1/certs",
                         "client_secret":GOOGLE_CLIENT_SECRET,
                         "redirect_uris":GOOGLE_REDIRECT_URIS
                        }
                }