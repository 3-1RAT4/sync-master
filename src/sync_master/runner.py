from pathlib import Path

from sync_master.agent.orchestrator import run_actions_for_video
from sync_master.config import load_settings, load_spotify_overrides
from sync_master.playlist_naming import parse_playlist_name
from sync_master.sources.youtube import diff_new_videos, fetch_my_playlists, fetch_playlist_items
from sync_master.state import acquire_lock, load_state, save_state
from sync_master.youtube_auth import build_oauth_client


def _needs_processing(video: dict) -> bool:
    actions = video["actions"]
    if not actions:
        return True
    return any(action.get("status") == "failed" for action in actions.values())


def perform_run(
    config_dir: Path,
    dry_run: bool = False,
    fetch_playlists_fn=fetch_my_playlists,
    fetch_items_fn=fetch_playlist_items,
    youtube_client_factory=build_oauth_client,
    action_runner=run_actions_for_video,
) -> dict:
    from dotenv import load_dotenv

    load_dotenv(config_dir / "credentials.env")

    state_path = config_dir / "state.json"
    lock_path = config_dir / "state.json.lock"

    with acquire_lock(lock_path):
        state = load_state(state_path)
        settings = load_settings(config_dir / "settings.yaml")
        overrides = load_spotify_overrides(config_dir / "spotify_overrides.json")
        output_base_dir = Path(settings["output_base_dir"])

        youtube_client = youtube_client_factory()
        playlists = fetch_playlists_fn(youtube_client)

        parsed_by_playlist_id = {}
        for playlist in playlists:
            parsed = parse_playlist_name(playlist.title)
            if parsed is None:
                continue
            parsed_by_playlist_id[playlist.playlist_id] = parsed

            fetched = fetch_items_fn(playlist.playlist_id, youtube_client=youtube_client)
            for item in diff_new_videos(state, fetched):
                state["videos"][item.video_id] = {
                    "playlist_id": item.playlist_id,
                    "title": item.title,
                    "published_at": item.published_at,
                    "actions": {},
                }

        for video_id, video in state["videos"].items():
            if not _needs_processing(video):
                continue

            parsed = parsed_by_playlist_id.get(video["playlist_id"])
            if parsed is None:
                continue

            action_runner(
                action_names=parsed.actions,
                video_id=video_id,
                output_dir=output_base_dir / parsed.folder_path / video_id,
                actions_state=video["actions"],
                dry_run=dry_run,
                video_title=video["title"],
                spotify_playlist_name=parsed.leaf_name,
                spotify_overrides=overrides,
            )

        save_state(state_path, state)

    return state
