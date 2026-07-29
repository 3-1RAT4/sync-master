import os
from pathlib import Path

SCOPE = "playlist-modify-public playlist-modify-private"
CACHE_PATH = Path.home() / ".config" / "sync-master" / ".spotify_cache"


def build_oauth_manager():
    from spotipy.oauth2 import SpotifyOAuth

    return SpotifyOAuth(
        client_id=os.environ.get("SPOTIFY_CLIENT_ID"),
        client_secret=os.environ.get("SPOTIFY_CLIENT_SECRET"),
        redirect_uri=os.environ.get("SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8080/callback"),
        scope=SCOPE,
        cache_path=str(CACHE_PATH),
    )
