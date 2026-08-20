import mimetypes
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from sync_master.db import repository
from sync_master.tools.download import download_video
from sync_master.tools.spotify_playlist import add_to_playlist, find_or_create_playlist
from sync_master.tools.spotify_search import search_track
from sync_master.tools.summarize import summarize
from sync_master.tools.transcript import get_transcript

DEFAULT_SUMMARIZE_INSTRUCTIONS = (
    "Summarize this transcript concisely, capturing the key points and main topics discussed."
)


@dataclass
class SimpleTool:
    name: str
    description: str
    func: Callable[[], str]


class NoMatchFound(Exception):
    pass


def _track_id_from_uri(uri: str) -> str:
    return uri.rsplit(":", 1)[-1] if uri.startswith("spotify:") else uri


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _wrap_action(name: str, action_fn, actions_state: dict, dry_run: bool, call_log: list) -> SimpleTool:
    # actions_state is the video's "actions" dict straight out of sync_state's
    # JSONB document (see runner.py) - mutated here, persisted wholesale by
    # runner.py's save_state_fn call, not written to the DB from in here.
    def run():
        if dry_run:
            call_log.append({"tool": name, "video_id": action_fn.video_id})
            return f"[dry-run] would run {name}"

        try:
            action_fn()
            actions_state[name] = {"status": "done", "updated_at": _now()}
            return f"{name} completed"
        except NoMatchFound:
            actions_state[name] = {"status": "no_match", "updated_at": _now()}
            return f"{name}: no match found"
        except Exception as exc:
            actions_state[name] = {"status": "failed", "updated_at": _now(), "error": str(exc)}
            return f"{name} failed: {exc}"

    return SimpleTool(name=name, description=f"Run the {name} action for this video.", func=run)


def make_action_tools(
    video_id: str,
    scratch_dir: Path,
    actions_state: dict,
    dry_run: bool,
    call_log: list,
    session=None,
    download_fn=download_video,
    transcript_fn=get_transcript,
    summarize_fn=summarize,
    search_track_fn=search_track,
    add_to_playlist_fn=add_to_playlist,
    find_or_create_playlist_fn=find_or_create_playlist,
    save_video_file_fn=repository.save_video_file,
    save_transcript_fn=repository.save_transcript,
    get_transcript_text_fn=repository.get_transcript_text,
    save_summary_fn=repository.save_summary,
    save_spotify_sync_fn=repository.save_spotify_sync,
    summarize_instructions: str = DEFAULT_SUMMARIZE_INSTRUCTIONS,
    spotify_playlist_name: str | None = None,
    video_title: str | None = None,
    spotify_overrides: dict | None = None,
) -> list[SimpleTool]:
    def download_action():
        path = download_fn(video_id, scratch_dir, title=video_title)
        content_type, _ = mimetypes.guess_type(path.name)
        save_video_file_fn(
            session, video_id, filename=path.name, content_type=content_type, content=path.read_bytes()
        )

    download_action.video_id = video_id

    def transcript_action():
        result = transcript_fn(video_id, scratch_dir, title=video_title)
        save_transcript_fn(session, video_id, result.source, result.text, result.segments)

    transcript_action.video_id = video_id

    def summarize_action():
        transcript_text = get_transcript_text_fn(session, video_id)
        if transcript_text is None:
            raise RuntimeError(f"No transcript stored for video {video_id}; run the transcript action first.")
        result = summarize_fn(transcript_text, summarize_instructions)
        save_summary_fn(
            session, video_id, result.content, summarize_instructions, result.llm_provider, result.llm_model
        )

    summarize_action.video_id = video_id

    def spotify_sync_action():
        override = (spotify_overrides or {}).get(video_id)
        matched_via = "override" if override else "search"

        if override and override.startswith("spotify:"):
            uri = override
        else:
            query = override or video_title or video_id
            uri = search_track_fn(query)

        if uri is None:
            raise NoMatchFound(video_id)

        playlist_id = find_or_create_playlist_fn(spotify_playlist_name)
        add_to_playlist_fn(playlist_id, uri)
        save_spotify_sync_fn(
            session, video_id, _track_id_from_uri(uri), uri, playlist_id, matched_via
        )

    spotify_sync_action.video_id = video_id

    return [
        _wrap_action("download", download_action, actions_state, dry_run, call_log),
        _wrap_action("transcript", transcript_action, actions_state, dry_run, call_log),
        _wrap_action("summarize", summarize_action, actions_state, dry_run, call_log),
        _wrap_action("spotify_sync", spotify_sync_action, actions_state, dry_run, call_log),
    ]


def run_actions_for_video(
    action_names: list[str],
    video_id: str,
    scratch_dir: Path,
    actions_state: dict,
    dry_run: bool = False,
    call_log: list | None = None,
    session=None,
    **tool_kwargs,
) -> list:
    call_log = call_log if call_log is not None else []
    tools_by_name = {
        tool.name: tool
        for tool in make_action_tools(
            video_id=video_id,
            scratch_dir=scratch_dir,
            actions_state=actions_state,
            dry_run=dry_run,
            call_log=call_log,
            session=session,
            **tool_kwargs,
        )
    }

    for name in action_names:
        if actions_state.get(name, {}).get("status") == "done":
            continue
        tools_by_name[name].func()

    return call_log
