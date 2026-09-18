from dataclasses import dataclass

_THUMBNAIL_PREFERENCE = ("maxres", "standard", "high", "medium", "default")


def _best_thumbnail_url(thumbnails: dict) -> str | None:
    for key in _THUMBNAIL_PREFERENCE:
        entry = thumbnails.get(key)
        if entry:
            return entry.get("url")
    return None


@dataclass(frozen=True)
class VideoItem:
    video_id: str
    title: str
    published_at: str
    playlist_id: str
    description: str = ""
    thumbnail_url: str | None = None
    # 0-based index within the playlist, as YouTube orders it. None only for
    # callers that build items by hand (tests, legacy migration).
    position: int | None = None


@dataclass(frozen=True)
class PlaylistInfo:
    playlist_id: str
    title: str
    description: str = ""
    thumbnail_url: str | None = None
    item_count: int | None = None
    published_at: str | None = None


def _build_client(api_key: str):
    from googleapiclient.discovery import build

    return build("youtube", "v3", developerKey=api_key)


def fetch_my_playlists(youtube_client) -> list[PlaylistInfo]:
    playlists: list[PlaylistInfo] = []
    request = youtube_client.playlists().list(
        part="snippet,contentDetails",
        mine=True,
        maxResults=50,
    )
    while request is not None:
        response = request.execute()
        for raw_item in response.get("items", []):
            snippet = raw_item["snippet"]
            playlists.append(
                PlaylistInfo(
                    playlist_id=raw_item["id"],
                    title=snippet["title"],
                    description=snippet.get("description", ""),
                    thumbnail_url=_best_thumbnail_url(snippet.get("thumbnails") or {}),
                    item_count=raw_item.get("contentDetails", {}).get("itemCount"),
                    published_at=snippet.get("publishedAt"),
                )
            )
        request = youtube_client.playlists().list_next(request, response)

    return playlists


def fetch_playlist_items(playlist_id: str, api_key: str | None = None, youtube_client=None) -> list[VideoItem]:
    client = youtube_client or _build_client(api_key)

    items: list[VideoItem] = []
    request = client.playlistItems().list(
        part="snippet,contentDetails",
        playlistId=playlist_id,
        maxResults=50,
    )
    while request is not None:
        response = request.execute()
        for raw_item in response.get("items", []):
            snippet = raw_item["snippet"]
            content_details = raw_item.get("contentDetails", {})
            items.append(
                VideoItem(
                    video_id=content_details.get("videoId") or raw_item["snippet"]["resourceId"]["videoId"],
                    title=snippet["title"],
                    # contentDetails.videoPublishedAt is sometimes absent (seen on
                    # real accounts, e.g. for a since-deleted/privated video still
                    # listed in a playlist) - fall back to when it was added to
                    # this playlist, which snippet.publishedAt always has.
                    published_at=content_details.get("videoPublishedAt") or snippet.get("publishedAt", ""),
                    playlist_id=playlist_id,
                    description=snippet.get("description", ""),
                    thumbnail_url=_best_thumbnail_url(snippet.get("thumbnails") or {}),
                    # snippet.position is the authoritative playlist order; the
                    # running index is the same thing unless a page is missing it.
                    position=snippet.get("position", len(items)),
                )
            )
        request = client.playlistItems().list_next(request, response)

    return items


def diff_new_videos(known_video_ids: set[str], fetched: list[VideoItem]) -> list[VideoItem]:
    return [item for item in fetched if item.video_id not in known_video_ids]


def rename_playlist(playlist_id: str, new_title: str, youtube_client) -> None:
    """Needs the read/write `youtube` scope (youtube_auth.py) - youtube.readonly
    can't call playlists.update. Fetches the existing snippet first and only
    changes `title` before writing it back - the API replaces the whole
    `snippet` part on update, so sending just {"title": ...} would silently
    wipe the playlist's description/tags/etc.
    """
    response = youtube_client.playlists().list(part="snippet", id=playlist_id).execute()
    items = response.get("items", [])
    if not items:
        raise ValueError(f"Playlist not found: {playlist_id}")

    snippet = items[0]["snippet"]
    snippet["title"] = new_title
    youtube_client.playlists().update(part="snippet", body={"id": playlist_id, "snippet": snippet}).execute()
