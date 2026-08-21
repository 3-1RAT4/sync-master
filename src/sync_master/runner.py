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
    upsert_video_fn=repository.upsert_video,
    load_state_fn=repository.load_state,
    save_state_fn=repository.save_state,
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
                if parsed is not None:
                    parsed_by_playlist_id[playlist.playlist_id] = parsed

                # Full catalog: every playlist gets cataloged, flagged/tracked
                # or not - folder_path/leaf_name/actions stay NULL for the rest.
                playlist_pk = upsert_playlist_fn(
                    session,
                    source="youtube",
                    external_id=playlist.playlist_id,
                    title=playlist.title,
                    description=playlist.description,
                    thumbnail_url=playlist.thumbnail_url,
                    item_count=playlist.item_count,
                    published_at=playlist.published_at,
                    folder_path=parsed.folder_path if parsed else None,
                    leaf_name=parsed.leaf_name if parsed else None,
                    actions=parsed.actions if parsed else None,
                )

                fetched = fetch_items_fn(playlist.playlist_id, youtube_client=youtube_client)

                # Full catalog: every video gets cataloged too, and this also
                # ensures the FK anchor exists before any action dispatch below.
                for item in fetched:
                    upsert_video_fn(
                        session,
                        source="youtube",
                        external_id=item.video_id,
                        playlist_id=playlist_pk,
                        title=item.title,
                        description=item.description,
                        thumbnail_url=item.thumbnail_url,
                        published_at=item.published_at,
                    )

                if parsed is None:
                    continue

                for item in diff_new_videos(state["videos"].keys(), fetched):
                    state["videos"][item.video_id] = {
                        "playlist_id": item.playlist_id,
                        "title": item.title,
                        "published_at": item.published_at,
                        "actions": {},
                    }

                # Refresh title/published_at for videos we already knew about too -
                # a video's owner can rename it after we've discovered it (not
                # something we control), and a stale cached title here would feed
                # wrong text into spotify_sync's search query, or a stale filename
                # into download/transcript. actions (processing status) is left
                # untouched - this only refreshes metadata, never reprocesses.
                for item in fetched:
                    video = state["videos"].get(item.video_id)
                    if video is not None:
                        video["title"] = item.title
                        video["published_at"] = item.published_at

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
