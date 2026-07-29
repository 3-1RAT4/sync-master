from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from sync_master.tools.download import download_video
from sync_master.tools.naming import transcript_filename
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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class NoMatchFound(Exception):
    pass


def _wrap_action(name: str, action_fn, actions_state: dict, dry_run: bool, call_log: list) -> SimpleTool:
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
    output_dir: Path,
    actions_state: dict,
    dry_run: bool,
    call_log: list,
    download_fn=download_video,
    transcript_fn=get_transcript,
    summarize_fn=summarize,
    search_track_fn=search_track,
    add_to_playlist_fn=add_to_playlist,
    find_or_create_playlist_fn=find_or_create_playlist,
    summarize_instructions: str = DEFAULT_SUMMARIZE_INSTRUCTIONS,
    spotify_playlist_name: str | None = None,
    video_title: str | None = None,
    spotify_overrides: dict | None = None,
) -> list[SimpleTool]:
    def download_action():
        download_fn(video_id, output_dir, title=video_title)

    download_action.video_id = video_id

    def transcript_action():
        transcript_fn(video_id, output_dir, title=video_title)

    transcript_action.video_id = video_id

    def summarize_action():
        transcript_path = output_dir / transcript_filename(video_title)
        transcript_text = transcript_path.read_text()
        summarize_fn(transcript_text, summarize_instructions, output_dir)

    summarize_action.video_id = video_id

    def spotify_sync_action():
        override = (spotify_overrides or {}).get(video_id)
        if override and override.startswith("spotify:"):
            uri = override
        else:
            query = override or video_title or video_id
            uri = search_track_fn(query)

        if uri is None:
            raise NoMatchFound(video_id)

        playlist_id = find_or_create_playlist_fn(spotify_playlist_name)
        add_to_playlist_fn(playlist_id, uri)

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
    output_dir: Path,
    actions_state: dict,
    dry_run: bool = False,
    call_log: list | None = None,
    **tool_kwargs,
) -> list:
    call_log = call_log if call_log is not None else []
    tools_by_name = {
        tool.name: tool
        for tool in make_action_tools(
            video_id=video_id,
            output_dir=output_dir,
            actions_state=actions_state,
            dry_run=dry_run,
            call_log=call_log,
            **tool_kwargs,
        )
    }

    for name in action_names:
        if actions_state.get(name, {}).get("status") == "done":
            continue
        tools_by_name[name].func()

    return call_log
