import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from sync_master.tools.download import download_video
from sync_master.tools.spotify_playlist import add_to_playlist
from sync_master.tools.spotify_search import search_track
from sync_master.tools.summarize import summarize
from sync_master.tools.transcript import get_transcript


@dataclass
class SimpleTool:
    name: str
    description: str
    func: Callable[[], str]


def build_prompt(policy_text: str, video: dict, actions_state: dict) -> str:
    return (
        f"{policy_text}\n\n"
        f"Video: {video.get('title')} (id: {video.get('video_id')}, "
        f"published: {video.get('published_at')})\n"
        f"Current action state: {json.dumps(actions_state)}\n"
    )


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
    policy_text: str = "",
    spotify_playlist_id: str | None = None,
    video_title: str | None = None,
    spotify_overrides: dict | None = None,
) -> list[SimpleTool]:
    def download_action():
        download_fn(video_id, output_dir)

    download_action.video_id = video_id

    def transcript_action():
        transcript_fn(video_id, output_dir)

    transcript_action.video_id = video_id

    def summarize_action():
        transcript_path = output_dir / "transcript.md"
        transcript_text = transcript_path.read_text()
        summarize_fn(transcript_text, policy_text, output_dir)

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

        add_to_playlist_fn(spotify_playlist_id, uri)

    spotify_sync_action.video_id = video_id

    return [
        _wrap_action("download", download_action, actions_state, dry_run, call_log),
        _wrap_action("transcript", transcript_action, actions_state, dry_run, call_log),
        _wrap_action("summarize", summarize_action, actions_state, dry_run, call_log),
        _wrap_action("spotify_sync", spotify_sync_action, actions_state, dry_run, call_log),
    ]


def to_langchain_tools(tools: list[SimpleTool]):
    from langchain_core.tools import StructuredTool

    return [
        StructuredTool.from_function(func=tool.func, name=tool.name, description=tool.description)
        for tool in tools
    ]


def run_agent_for_video(
    llm,
    policy_text: str,
    video: dict,
    actions_state: dict,
    output_dir: Path,
    dry_run: bool = False,
    call_log: list | None = None,
    spotify_playlist_id: str | None = None,
    spotify_overrides: dict | None = None,
) -> list:
    from langgraph.prebuilt import create_react_agent

    call_log = call_log if call_log is not None else []
    tools = make_action_tools(
        video_id=video["video_id"],
        output_dir=output_dir,
        actions_state=actions_state,
        dry_run=dry_run,
        call_log=call_log,
        policy_text=policy_text,
        spotify_playlist_id=spotify_playlist_id,
        video_title=video.get("title"),
        spotify_overrides=spotify_overrides,
    )
    agent = create_react_agent(llm, to_langchain_tools(tools))
    prompt = build_prompt(policy_text, video, actions_state)
    agent.invoke({"messages": [{"role": "user", "content": prompt}]})
    return call_log
