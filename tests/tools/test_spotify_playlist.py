from sync_master.tools.spotify_playlist import add_to_playlist, find_or_create_playlist


class FakeSpotifyClient:
    def __init__(self):
        self.calls = []

    def playlist_add_items(self, playlist_id, items):
        self.calls.append((playlist_id, items))


def test_add_to_playlist_calls_playlist_add_items_with_uri():
    client = FakeSpotifyClient()

    add_to_playlist("spotify:playlist:xyz", "spotify:track:abc123", spotify_client=client)

    assert client.calls == [("spotify:playlist:xyz", ["spotify:track:abc123"])]


class FakePlaylistClient:
    def __init__(self, pages, user_id="user123"):
        self._pages = pages
        self._user_id = user_id
        self.created = []

    def current_user_playlists(self, limit=50, offset=0):
        page_index = offset // limit
        if page_index >= len(self._pages):
            return {"items": []}
        return {"items": self._pages[page_index]}

    def current_user(self):
        return {"id": self._user_id}

    def user_playlist_create(self, user_id, name, public=False):
        self.created.append((user_id, name, public))
        return {"id": "spotify:playlist:newly-created"}


def test_find_or_create_playlist_returns_existing_playlist_id_when_found():
    client = FakePlaylistClient(
        pages=[[{"id": "spotify:playlist:existing", "name": "PARTY"}]],
    )

    playlist_id = find_or_create_playlist("PARTY", spotify_client=client)

    assert playlist_id == "spotify:playlist:existing"
    assert client.created == []


def test_find_or_create_playlist_finds_match_across_pages():
    client = FakePlaylistClient(
        pages=[
            [{"id": "spotify:playlist:other", "name": "OTHER"}] * 50,
            [{"id": "spotify:playlist:existing", "name": "PARTY"}],
        ],
    )

    playlist_id = find_or_create_playlist("PARTY", spotify_client=client)

    assert playlist_id == "spotify:playlist:existing"


def test_find_or_create_playlist_creates_new_playlist_when_not_found():
    client = FakePlaylistClient(pages=[[{"id": "spotify:playlist:other", "name": "OTHER"}]])

    playlist_id = find_or_create_playlist("PARTY", spotify_client=client)

    assert playlist_id == "spotify:playlist:newly-created"
    assert client.created == [("user123", "PARTY", False)]
