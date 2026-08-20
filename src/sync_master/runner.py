from pathlib import Path

from sync_master.agent.orchestrator import run_actions_for_video
from sync_master.config import load_settings, load_spotify_overrides
from sync_master.db import repository
from sync_master.db.engine import get_session
from sync_master.playlist_naming import parse_playlist_name
from sync_master.sources.youtube import diff_new_videos, fetch_my_playlists, fetch_playlist_items
from sync_master.youtube_auth import build_oauth_client


def _needs_processing(video: dict, required_actions: list[str]) -> bool:
    actions = video["actions"]
    for name in required_actions:
        status = actions.get(name, {}).get("status")
        if status not in ("done", "no_match"):
            return True
    return False


def perform_run(
    config_dir: Path,
    dry_run: bool = False,
    fetch_playlists_fn=fetch_my_playlists,
    fetch_items_fn=fetch_playlist_items,
    youtube_client_factory=build_oauth_client,
    action_runner=run_actions_for_video,
    run_log: list | None = None,
    session_factory=get_session,
    acquire_run_lock=repository.acquire_run_lock,
    upsert_playlist_fn=repository.upsert_playlist,
    load_state_fn=repository.load_state,
    save_state_fn=repository.save_state,
    ensure_video_row_fn=repository.ensure_video_row,
) -> None:
    from dotenv import load_dotenv

    load_dotenv(config_dir / "credentials.env")

    session = session_factory()
    try:
        with acquire_run_lock(session):
            settings = load_settings(config_dir / "settings.yaml")
            overrides = load_spotify_overrides(config_dir / "spotify_overrides.json")
            scratch_dir = Path(settings["output_base_dir"])

            state = load_state_fn(session)

            youtube_client = youtube_client_factory()
            playlists = fetch_playlists_fn(youtube_client)

            parsed_by_playlist_id = {}
            for playlist in playlists:
                parsed = parse_playlist_name(playlist.title)
                if parsed is None:
                    continue
                parsed_by_playlist_id[playlist.playlist_id] = parsed
                upsert_playlist_fn(
                    session,
                    youtube_playlist_id=playlist.playlist_id,
                    title=playlist.title,
                    folder_path=parsed.folder_path,
                    leaf_name=parsed.leaf_name,
                    actions=parsed.actions,
                )

                fetched = fetch_items_fn(playlist.playlist_id, youtube_client=youtube_client)
                for item in diff_new_videos(state["videos"].keys(), fetched):
                    ensure_video_row_fn(session, item.video_id)
                    state["videos"][item.video_id] = {
                        "playlist_id": item.playlist_id,
                        "title": item.title,
                        "published_at": item.published_at,
                        "actions": {},
                    }

            for video_id, video in state["videos"].items():
                parsed = parsed_by_playlist_id.get(video["playlist_id"])
                if parsed is None:
                    continue

                if not _needs_processing(video, parsed.actions):
                    continue

                call_log: list = []
                action_runner(
                    action_names=parsed.actions,
                    video_id=video_id,
                    scratch_dir=scratch_dir / parsed.folder_path / video_id,
                    actions_state=video["actions"],
                    dry_run=dry_run,
                    video_title=video["title"],
                    spotify_playlist_name=parsed.leaf_name,
                    spotify_overrides=overrides,
                    call_log=call_log,
                    session=session,
                )

                if not dry_run:
                    # Saved per-video rather than only once at the very end (unlike
                    # the original file-based design) so a crash mid-run loses at
                    # most the video in flight, not all progress made so far.
                    save_state_fn(session, state)

                if run_log is not None:
                    run_log.append(
                        {
                            "video_id": video_id,
                            "title": video["title"],
                            "folder_path": str(parsed.folder_path),
                            "actions": parsed.actions,
                            "call_log": call_log,
                        }
                    )

            if not dry_run:
                # Also covers newly-discovered videos when nothing needed
                # dispatching (e.g. every flagged action already done/no_match).
                save_state_fn(session, state)
    finally:
        session.close()
