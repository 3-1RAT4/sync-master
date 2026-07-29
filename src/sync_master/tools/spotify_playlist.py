def _default_client():
    import spotipy

    from sync_master.spotify_auth import build_oauth_manager

    return spotipy.Spotify(auth_manager=build_oauth_manager())


def add_to_playlist(playlist_id: str, track_uri: str, spotify_client=None) -> None:
    client = spotify_client or _default_client()
    client.playlist_add_items(playlist_id, [track_uri])


def find_or_create_playlist(name: str, spotify_client=None) -> str:
    client = spotify_client or _default_client()

    limit = 50
    offset = 0
    while True:
        response = client.current_user_playlists(limit=limit, offset=offset)
        items = response.get("items", [])
        for item in items:
            if item["name"] == name:
                return item["id"]
        if len(items) < limit:
            break
        offset += limit

    user_id = client.current_user()["id"]
    created = client.user_playlist_create(user_id, name, public=False)
    return created["id"]
