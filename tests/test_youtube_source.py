from sync_master.sources.youtube import (
    PlaylistInfo,
    VideoItem,
    diff_new_videos,
    fetch_my_playlists,
    fetch_playlist_items,
)


class FakePlaylistItemsRequest:
    def __init__(self, pages, index):
        self._pages = pages
        self._index = index

    def execute(self):
        return self._pages[self._index]


class FakePlaylistItemsResource:
    def __init__(self, pages):
        self._pages = pages

    def list(self, **kwargs):
        return FakePlaylistItemsRequest(self._pages, index=0)

    def list_next(self, previous_request, response):
        if response.get("nextPageToken"):
            return FakePlaylistItemsRequest(self._pages, index=previous_request._index + 1)
        return None


class FakePlaylistsRequest:
    def __init__(self, pages, index):
        self._pages = pages
        self._index = index

    def execute(self):
        return self._pages[self._index]


class FakePlaylistsResource:
    def __init__(self, pages):
        self._pages = pages

    def list(self, **kwargs):
        return FakePlaylistsRequest(self._pages, index=0)

    def list_next(self, previous_request, response):
        if response.get("nextPageToken"):
            return FakePlaylistsRequest(self._pages, index=previous_request._index + 1)
        return None


class FakeYoutubeClient:
    def __init__(self, pages=None, playlist_pages=None):
        self._pages = pages
        self._playlist_pages = playlist_pages

    def playlistItems(self):
        return FakePlaylistItemsResource(self._pages)

    def playlists(self):
        return FakePlaylistsResource(self._playlist_pages)


def _item(video_id, title, published_at):
    return {
        "contentDetails": {"videoId": video_id, "videoPublishedAt": published_at},
        "snippet": {"title": title},
    }


def test_fetch_playlist_items_returns_video_items_from_single_page():
    client = FakeYoutubeClient(
        pages=[
            {
                "items": [_item("v1", "Video One", "2026-01-01T00:00:00Z")],
                "nextPageToken": None,
            }
        ]
    )

    items = fetch_playlist_items("PL123", youtube_client=client)

    assert items == [
        VideoItem(
            video_id="v1",
            title="Video One",
            published_at="2026-01-01T00:00:00Z",
            playlist_id="PL123",
        )
    ]


def test_fetch_playlist_items_follows_pagination_across_pages():
    client = FakeYoutubeClient(
        pages=[
            {
                "items": [_item("v1", "Video One", "2026-01-01T00:00:00Z")],
                "nextPageToken": "token2",
            },
            {
                "items": [_item("v2", "Video Two", "2026-01-02T00:00:00Z")],
                "nextPageToken": None,
            },
        ]
    )

    items = fetch_playlist_items("PL123", youtube_client=client)

    assert [item.video_id for item in items] == ["v1", "v2"]


def test_diff_new_videos_excludes_videos_already_in_state():
    state = {"videos": {"v1": {"title": "Already seen"}}}
    fetched = [
        VideoItem(video_id="v1", title="Already seen", published_at="...", playlist_id="PL123"),
        VideoItem(video_id="v2", title="New video", published_at="...", playlist_id="PL123"),
    ]

    new_items = diff_new_videos(state, fetched)

    assert [item.video_id for item in new_items] == ["v2"]


def _playlist(playlist_id, title):
    return {"id": playlist_id, "snippet": {"title": title}}


def test_fetch_my_playlists_returns_playlist_info_from_single_page():
    client = FakeYoutubeClient(
        playlist_pages=[
            {
                "items": [_playlist("PL123", "My Playlist[!]")],
                "nextPageToken": None,
            }
        ]
    )

    playlists = fetch_my_playlists(youtube_client=client)

    assert playlists == [PlaylistInfo(playlist_id="PL123", title="My Playlist[!]")]


def test_fetch_my_playlists_follows_pagination_across_pages():
    client = FakeYoutubeClient(
        playlist_pages=[
            {"items": [_playlist("PL1", "First")], "nextPageToken": "token2"},
            {"items": [_playlist("PL2", "Second")], "nextPageToken": None},
        ]
    )

    playlists = fetch_my_playlists(youtube_client=client)

    assert [p.playlist_id for p in playlists] == ["PL1", "PL2"]
