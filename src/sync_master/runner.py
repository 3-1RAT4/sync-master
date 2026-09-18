from dataclasses import dataclass, field, replace
from pathlib import Path

from sync_master.agent.orchestrator import needs_processing, run_actions_for_video
from sync_master.config import load_settings, load_spotify_overrides
from sync_master.playlist_naming import parse_playlist_name
from sync_master.sources.youtube import fetch_my_playlists, fetch_playlist_items
from sync_master.state import acquire_lock, load_state, save_state
from sync_master.vault import VAULT_SUBDIR, VaultIndex, VideoFolder, entry_name, place_video, playlist_dir
from sync_master.youtube_auth import build_oauth_client


@dataclass
class RunReport:
    playlists: int = 0
    videos: int = 0
    created: int = 0
    moved: int = 0
    processed: list = field(default_factory=list)


def perform_run(
    config_dir: Path,
    dry_run: bool = False,
    fetch_playlists_fn=fetch_my_playlists,
    fetch_items_fn=fetch_playlist_items,
    youtube_client_factory=build_oauth_client,
    action_runner=run_actions_for_video,
    run_log: list | None = None,
    vault_dir: Path | None = None,
) -> RunReport:
    """One sync. Two phases, like before: first every playlist and video is
    placed in the vault (that *is* the catalog - a folder and a note per
    video, renamed into place if YouTube reordered or retitled it), then the
    flagged playlists' videos get their actions run. Nothing is written in a
    dry run, not even notes.
    """
    from dotenv import load_dotenv

    load_dotenv(config_dir / "credentials.env")
    settings = load_settings(config_dir / "settings.yaml")
    overrides = load_spotify_overrides(config_dir / "spotify_overrides.json")
    scratch_dir = Path(settings["output_base_dir"])
    root = (vault_dir or Path(settings["vault_dir"]).expanduser()) / VAULT_SUBDIR

    state_path = config_dir / "state.json"
    report = RunReport()
    run_log = report.processed if run_log is None else run_log

    with acquire_lock(config_dir / "state.json.lock"):
        state = load_state(state_path)
        youtube_client = youtube_client_factory()
        index = VaultIndex.scan(root)

        # Phase 1: the catalog. Every playlist, every video, a folder each.
        pending = []  # (parsed, item, vf) for videos in flagged playlists
        for playlist in fetch_playlists_fn(youtube_client):
            report.playlists += 1
            parsed = parse_playlist_name(playlist.title)

            for position, item in enumerate(fetch_items_fn(playlist.playlist_id, youtube_client=youtube_client)):
                if item.position is None:
                    item = replace(item, position=position)
                report.videos += 1

                if dry_run:
                    existing = index.find(playlist.playlist_id, item.video_id)
                    name = entry_name(item.position, item.title)
                    target = playlist_dir(root, playlist.title) / name
                    if existing is None:
                        report.created += 1
                        vf = VideoFolder(target, name)
                    else:
                        report.moved += existing.resolve() != target.resolve()
                        vf = VideoFolder(existing, existing.name)
                else:
                    placement = place_video(index, playlist, item)
                    report.created += placement.created
                    report.moved += placement.moved_from is not None
                    vf = placement.folder

                if parsed is not None:
                    pending.append((parsed, item, vf, playlist.playlist_id))

        # Phase 2: actions, for videos in flagged playlists only.
        for parsed, item, vf, playlist_id in pending:
            video = state["videos"].setdefault(item.video_id, {"actions": {}})
            # Refresh metadata on every run - an owner can rename a video after
            # we first saw it, and a stale title would feed spotify_sync's
            # search. Action status is left alone; this never reprocesses.
            video.update({"playlist_id": playlist_id, "title": item.title, "published_at": item.published_at})

            if not needs_processing(video["actions"], parsed.actions, vf):
                continue

            call_log: list = []
            action_runner(
                action_names=parsed.actions,
                video_id=item.video_id,
                scratch_dir=scratch_dir / parsed.folder_path / item.video_id,
                actions_state=video["actions"],
                dry_run=dry_run,
                video_title=item.title,
                spotify_playlist_name=parsed.leaf_name,
                spotify_overrides=overrides,
                call_log=call_log,
                vf=vf,
                spotify_playlist_cache=state["spotify_playlists"],
            )

            if not dry_run:
                # Per video, not once at the end, so a crash mid-run loses at
                # most the video in flight.
                save_state(state_path, state)

            run_log.append(
                {
                    "video_id": item.video_id,
                    "title": item.title,
                    "folder_path": str(parsed.folder_path),
                    "actions": parsed.actions,
                    "call_log": call_log,
                }
            )

        if not dry_run:
            # Also covers metadata refreshes when nothing needed dispatching.
            save_state(state_path, state)

    return report
