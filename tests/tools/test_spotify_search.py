from sync_master.tools.spotify_search import search_track


class FakeSpotifyClient:
    def __init__(self, results):
        self.results = results
        self.received_query = None

    def search(self, q, type="track", limit=1):
        self.received_query = q
        return self.results


def test_search_track_returns_uri_when_match_found():
    client = FakeSpotifyClient(
        results={"tracks": {"items": [{"uri": "spotify:track:abc123"}]}}
    )

    uri = search_track("My Podcast Episode", spotify_client=client)

    assert uri == "spotify:track:abc123"
    assert client.received_query == "My Podcast Episode"


def test_search_track_returns_none_when_no_match():
    client = FakeSpotifyClient(results={"tracks": {"items": []}})

    uri = search_track("Nonexistent Episode", spotify_client=client)

    assert uri is None
