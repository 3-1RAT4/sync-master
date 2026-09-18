from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from sync_master import vault
from sync_master.tools.download import download_video
from sync_master.tools.spotify_playlist import add_to_playlist, find_or_create_playlist
from sync_master.tools.spotify_search import search_track
from sync_master.tools.summarize import summarize
from sync_master.tools.transcript import get_transcript
from sync_master.vault import VideoFolder

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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def needs_processing(actions_state: dict, action_names: list[str], vf: VideoFolder | None = None) -> bool:
    """An action is finished when the ledger says done *and* its product is
    in the vault. The vault wins: a summary deleted in Obsidian gets
    regenerated on the next run. no_match (Spotify found nothing) is final."""
    for name in action_names:
        status = actions_state.get(name, {}).get("status")
        if status == "no_match":
            continue
        if status == "done" and (vf is None or vf.has_output(name)):
            continue
        return True
    return False


def _wrap_action(name: str, action_fn, actions_state: dict, dry_run: bool, call_log: list) -> SimpleTool:
    # actions_state is the video's "actions" dict from state.json (see
    # runner.py) - mutated here, persisted by the runner, never written from
    # in here.
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
    vf: VideoFolder | None = None,
    download_fn=download_video,
    transcript_fn=get_transcript,
    summarize_fn=summarize,
    search_track_fn=search_track,
    add_to_playlist_fn=add_to_playlist,
    find_or_create_playlist_fn=find_or_create_playlist,
    store_video_fn=vault.store_video,
    store_transcript_fn=vault.store_transcript,
    read_transcript_fn=vault.read_transcript_text,
    store_summary_fn=vault.store_summary,
    record_spotify_sync_fn=vault.record_spotify_sync,
    spotify_playlist_cache: dict | None = None,
    summarize_instructions: str = DEFAULT_SUMMARIZE_INSTRUCTIONS,
    spotify_playlist_name: str | None = None,
    video_title: str | None = None,
    spotify_overrides: dict | None = None,
) -> list[SimpleTool]:
    # state.json's "spotify_playlists" section: playlist name -> Spotify id,
    # so find_or_create_playlist's search runs once per name, not per video.
    playlist_cache = spotify_playlist_cache if spotify_playlist_cache is not None else {}
    title = video_title or video_id

    def download_action():
        # yt-dlp writes to scratch (whisper/pyannote read it from there);
        # the vault gets a copy next to the note.
        path = download_fn(video_id, scratch_dir, title=video_title)
        store_video_fn(vf, path)

    download_action.video_id = video_id

    def transcript_action():
        result = transcript_fn(video_id, scratch_dir, title=video_title)
        store_transcript_fn(vf, result.text, result.source, title)

    transcript_action.video_id = video_id

    def summarize_action():
        if vf is None or not vf.transcript.exists():
            raise RuntimeError(f"No transcript in the vault for video {video_id}; run the transcript action first.")
        result = summarize_fn(read_transcript_fn(vf.transcript), summarize_instructions)
        store_summary_fn(vf, result.content, result.llm_provider, result.llm_model, title)

    summarize_action.video_id = video_id

    def spotify_sync_action():
        override = (spotify_overrides or {}).get(video_id)
        matched_via = "override" if override else "search"

        if override and override.startswith("spotify:"):
            uri = override
        else:
            uri = search_track_fn(override or video_title or video_id)

        if uri is None:
            raise NoMatchFound(video_id)

        playlist_id = playlist_cache.get(spotify_playlist_name)
        if playlist_id is None:
            playlist_id = find_or_create_playlist_fn(spotify_playlist_name)
            playlist_cache[spotify_playlist_name] = playlist_id
        add_to_playlist_fn(playlist_id, uri)
        record_spotify_sync_fn(vf, uri, playlist_id, matched_via)

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
    vf: VideoFolder | None = None,
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
            vf=vf,
            **tool_kwargs,
        )
    }

    for name in action_names:
        if not needs_processing(actions_state, [name], vf):
            continue
        tools_by_name[name].func()

    return call_log
