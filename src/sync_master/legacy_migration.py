"""One-time import of a pre-Postgres install's state.json + output directory
tree into the database. Only needed once per existing install; new installs
have nothing to migrate.
"""

import json
import mimetypes
from pathlib import Path

from sync_master.config import load_settings
from sync_master.db import repository
from sync_master.db.engine import get_session
from sync_master.playlist_naming import ParsedPlaylist, parse_playlist_name
from sync_master.sources.youtube import fetch_my_playlists
from sync_master.tools.naming import sanitize_filename
from sync_master.youtube_auth import build_oauth_client


def migrate_legacy_state(
    session,
    state_path: Path,
    output_dir: Path,
    youtube_client=None,
    fetch_playlists_fn=fetch_my_playlists,
) -> dict[str, int]:
    """Read an old state.json + its output directory and insert the equivalent
    rows into Postgres. Safe to re-run (repository writes are all upserts).

    `youtube_client`, if given, is used to look up each playlist's current
    title (needed to re-derive folder_path/leaf_name/actions via
    parse_playlist_name) - pass None to skip this and fall back to a
    placeholder playlist named after its raw playlist_id (e.g. for playlists
    that have since been renamed or deleted).
    """
    legacy_state = json.loads(state_path.read_text()) if state_path.exists() else {"videos": {}}

    playlist_titles: dict[str, str] = {}
    if youtube_client is not None:
        for playlist in fetch_playlists_fn(youtube_client):
            playlist_titles[playlist.playlist_id] = playlist.title

    parsed_by_playlist: dict[str, ParsedPlaylist] = {}
    counts = {"playlists": 0, "videos": 0, "actions": 0, "video_files": 0, "transcripts": 0, "summaries": 0}

    # state.json's per-video shape is now identical to sync_state.data's, so this
    # is a direct merge (legacy entries win on conflict) rather than row-by-row
    # record_* calls - see db/repository.py:load_state/save_state.
    current_state = repository.load_state(session)
    current_state.setdefault("videos", {})

    for video_id, video in legacy_state.get("videos", {}).items():
        playlist_id = video["playlist_id"]

        if playlist_id not in parsed_by_playlist:
            title = playlist_titles.get(playlist_id, playlist_id)
            parsed = parse_playlist_name(title) or ParsedPlaylist(
                folder_path=Path(playlist_id), leaf_name=playlist_id, actions=[]
            )
            parsed_by_playlist[playlist_id] = parsed
            repository.upsert_playlist(
                session,
                youtube_playlist_id=playlist_id,
                title=title,
                folder_path=parsed.folder_path,
                leaf_name=parsed.leaf_name,
                actions=parsed.actions,
            )
            counts["playlists"] += 1

        parsed = parsed_by_playlist[playlist_id]
        repository.ensure_video_row(session, video_id)
        current_state["videos"][video_id] = video
        counts["videos"] += 1
        counts["actions"] += len(video.get("actions", {}))

        video_dir = output_dir / parsed.folder_path / video_id
        if not video_dir.is_dir():
            continue

        base_name = sanitize_filename(video["title"]) if video.get("title") else "video"

        video_files = [path for path in video_dir.glob(f"{base_name}.*") if not path.name.endswith(".md")]
        if video_files:
            path = video_files[0]
            content_type, _ = mimetypes.guess_type(path.name)
            repository.save_video_file(
                session, video_id, filename=path.name, content_type=content_type, content=path.read_bytes()
            )
            counts["video_files"] += 1

        transcript_name = f"{base_name}_TRANSCRIPT.md" if video.get("title") else "transcript.md"
        transcript_path = video_dir / transcript_name
        if transcript_path.exists():
            # Legacy transcripts never recorded whether they came from captions
            # or Whisper, and per-speaker segments were only ever baked into
            # this text, never stored separately - both are genuinely
            # unrecoverable here, hence "unknown" and an empty segment list.
            repository.save_transcript(
                session, video_id, source="unknown", text_=transcript_path.read_text(), segments=[]
            )
            counts["transcripts"] += 1

        summary_path = video_dir / "summary.md"
        if summary_path.exists():
            repository.save_summary(
                session,
                video_id,
                content=summary_path.read_text(),
                instructions="(migrated from legacy output directory; original instructions not recorded)",
                llm_provider="unknown",
                llm_model="unknown",
            )
            counts["summaries"] += 1

    repository.save_state(session, current_state)

    return counts


def run_legacy_migration(
    config_dir: Path,
    output_dir: Path | None = None,
    session_factory=get_session,
    youtube_client_factory=build_oauth_client,
) -> dict[str, int]:
    from dotenv import load_dotenv

    load_dotenv(config_dir / "credentials.env")

    resolved_output_dir = output_dir
    if resolved_output_dir is None:
        settings = load_settings(config_dir / "settings.yaml")
        resolved_output_dir = Path(settings["output_base_dir"])

    try:
        youtube_client = youtube_client_factory()
    except Exception:
        # Playlist titles just won't be resolved; migrated playlists fall
        # back to a placeholder name derived from their raw playlist_id.
        youtube_client = None

    session = session_factory()
    try:
        return migrate_legacy_state(session, config_dir / "state.json", resolved_output_dir, youtube_client=youtube_client)
    finally:
        session.close()
