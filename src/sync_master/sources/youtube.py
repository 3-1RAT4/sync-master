from dataclasses import dataclass


@dataclass(frozen=True)
class VideoItem:
    video_id: str
    title: str
    published_at: str
    playlist_id: str


@dataclass(frozen=True)
class PlaylistInfo:
    playlist_id: str
    title: str


def _build_client(api_key: str):
    from googleapiclient.discovery import build

    return build("youtube", "v3", developerKey=api_key)


def fetch_my_playlists(youtube_client) -> list[PlaylistInfo]:
    playlists: list[PlaylistInfo] = []
    request = youtube_client.playlists().list(
        part="snippet",
        mine=True,
        maxResults=50,
    )
    while request is not None:
        response = request.execute()
        for raw_item in response.get("items", []):
            playlists.append(
                PlaylistInfo(
                    playlist_id=raw_item["id"],
                    title=raw_item["snippet"]["title"],
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
            items.append(
                VideoItem(
                    video_id=raw_item["contentDetails"]["videoId"],
                    title=raw_item["snippet"]["title"],
                    published_at=raw_item["contentDetails"]["videoPublishedAt"],
                    playlist_id=playlist_id,
                )
            )
        request = client.playlistItems().list_next(request, response)

    return items


def diff_new_videos(state: dict, fetched: list[VideoItem]) -> list[VideoItem]:
    known_ids = state.get("videos", {}).keys()
    return [item for item in fetched if item.video_id not in known_ids]
