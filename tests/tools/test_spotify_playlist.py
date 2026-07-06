from sync_master.tools.spotify_playlist import add_to_playlist


class FakeSpotifyClient:
    def __init__(self):
        self.calls = []

    def playlist_add_items(self, playlist_id, items):
        self.calls.append((playlist_id, items))


def test_add_to_playlist_calls_playlist_add_items_with_uri():
    client = FakeSpotifyClient()

    add_to_playlist("spotify:playlist:xyz", "spotify:track:abc123", spotify_client=client)

    assert client.calls == [("spotify:playlist:xyz", ["spotify:track:abc123"])]
