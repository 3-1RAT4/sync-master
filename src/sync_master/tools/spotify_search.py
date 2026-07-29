def _default_client():
    import spotipy

    from sync_master.spotify_auth import build_oauth_manager

    return spotipy.Spotify(auth_manager=build_oauth_manager())


def search_track(query: str, spotify_client=None) -> str | None:
    client = spotify_client or _default_client()

    results = client.search(q=query, type="track", limit=1)
    items = results.get("tracks", {}).get("items", [])
    if not items:
        return None
    return items[0]["uri"]
