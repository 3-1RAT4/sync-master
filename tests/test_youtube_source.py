import pytest

from sync_master.sources.youtube import (
    PlaylistInfo,
    VideoItem,
    diff_new_videos,
    fetch_my_playlists,
    fetch_playlist_items,
    rename_playlist,
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
            # No snippet.position in this fake page, so the running index stands in.
            position=0,
        )
    ]


def test_fetch_playlist_items_takes_position_from_the_snippet_when_present():
    first = _item("v1", "Video One", "2026-01-01T00:00:00Z")
    second = _item("v2", "Video Two", "2026-01-02T00:00:00Z")
    first["snippet"]["position"] = 7
    second["snippet"]["position"] = 8
    client = FakeYoutubeClient(pages=[{"items": [first, second], "nextPageToken": None}])

    items = fetch_playlist_items("PL123", youtube_client=client)

    # YouTube's own playlist order, not where the item landed in our list.
    assert [item.position for item in items] == [7, 8]


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


def test_diff_new_videos_excludes_already_known_video_ids():
    known_video_ids = {"v1"}
    fetched = [
        VideoItem(video_id="v1", title="Already seen", published_at="...", playlist_id="PL123"),
        VideoItem(video_id="v2", title="New video", published_at="...", playlist_id="PL123"),
    ]

    new_items = diff_new_videos(known_video_ids, fetched)

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


class _FakeExecutable:
    def __init__(self, result):
        self._result = result

    def execute(self):
        return self._result


class FakeRenamePlaylistsResource:
    def __init__(self, existing_snippet):
        self._existing_snippet = existing_snippet
        self.update_calls = []

    def list(self, part=None, id=None):
        if self._existing_snippet is None:
            return _FakeExecutable({"items": []})
        return _FakeExecutable({"items": [{"id": id, "snippet": dict(self._existing_snippet)}]})

    def update(self, part=None, body=None):
        self.update_calls.append(body)
        return _FakeExecutable(body)


class FakeRenameClient:
    def __init__(self, existing_snippet):
        self.playlists_resource = FakeRenamePlaylistsResource(existing_snippet)

    def playlists(self):
        return self.playlists_resource


def test_rename_playlist_updates_title_while_preserving_other_snippet_fields():
    client = FakeRenameClient(
        existing_snippet={"title": "OLD-NAME[!]", "description": "keep me", "tags": ["a", "b"]}
    )

    rename_playlist("PL123", "NEW-NAME[!]", youtube_client=client)

    assert client.playlists_resource.update_calls == [
        {
            "id": "PL123",
            "snippet": {"title": "NEW-NAME[!]", "description": "keep me", "tags": ["a", "b"]},
        }
    ]


def test_rename_playlist_raises_when_playlist_not_found():
    client = FakeRenameClient(existing_snippet=None)

    with pytest.raises(ValueError):
        rename_playlist("PL_MISSING", "NEW-NAME", youtube_client=client)
