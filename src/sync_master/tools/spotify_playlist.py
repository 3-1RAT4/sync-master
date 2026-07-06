def _default_client():
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth

    return spotipy.Spotify(auth_manager=SpotifyOAuth())


def add_to_playlist(playlist_id: str, track_uri: str, spotify_client=None) -> None:
    client = spotify_client or _default_client()
    client.playlist_add_items(playlist_id, [track_uri])
