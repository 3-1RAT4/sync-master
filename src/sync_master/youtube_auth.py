import os

SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]


def build_oauth_client():
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials(
        token=None,
        refresh_token=os.environ.get("YOUTUBE_OAUTH_REFRESH_TOKEN"),
        client_id=os.environ.get("YOUTUBE_OAUTH_CLIENT_ID"),
        client_secret=os.environ.get("YOUTUBE_OAUTH_CLIENT_SECRET"),
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    return build("youtube", "v3", credentials=credentials)


def run_oauth_login_flow(client_id: str, client_secret: str) -> str:
    from google_auth_oauthlib.flow import InstalledAppFlow

    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    credentials = flow.run_local_server(port=0)
    return credentials.refresh_token
