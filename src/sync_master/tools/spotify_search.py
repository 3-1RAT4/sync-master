def _default_client():
    import spotipy
    from spotipy.oauth2 import SpotifyOAuth

    return spotipy.Spotify(auth_manager=SpotifyOAuth())


def search_track(query: str, spotify_client=None) -> str | None:
    client = spotify_client or _default_client()

    results = client.search(q=query, type="track", limit=1)
    items = results.get("tracks", {}).get("items", [])
    if not items:
        return None
    return items[0]["uri"]
