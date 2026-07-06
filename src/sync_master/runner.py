import os
from pathlib import Path

from sync_master.agent.orchestrator import run_agent_for_video
from sync_master.config import load_llm_config, load_spotify_overrides, load_sources
from sync_master.sources.youtube import diff_new_videos, fetch_playlist_items
from sync_master.state import acquire_lock, load_state, save_state


def _default_llm_factory(llm_config: dict):
    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=llm_config["model"],
        base_url=llm_config.get("base_url"),
        api_key=os.environ.get("LLM_API_KEY"),
    )


def _needs_processing(video: dict) -> bool:
    actions = video["actions"]
    if not actions:
        return True
    return any(action.get("status") == "failed" for action in actions.values())


def perform_run(
    config_dir: Path,
    dry_run: bool = False,
    fetch_fn=fetch_playlist_items,
    llm_factory=_default_llm_factory,
    agent_runner=run_agent_for_video,
) -> dict:
    from dotenv import load_dotenv

    load_dotenv(config_dir / "credentials.env")

    state_path = config_dir / "state.json"
    lock_path = config_dir / "state.json.lock"

    with acquire_lock(lock_path):
        state = load_state(state_path)
        sources = load_sources(config_dir / "sources")
        llm_config = load_llm_config(config_dir / "llm.yaml")
        overrides = load_spotify_overrides(config_dir / "spotify_overrides.json")
        source_by_playlist = {source.playlist_id: source for source in sources}

        for source in sources:
            fetched = fetch_fn(source.playlist_id, api_key=os.environ.get("YOUTUBE_API_KEY"))
            for item in diff_new_videos(state, fetched):
                state["videos"][item.video_id] = {
                    "playlist_id": item.playlist_id,
                    "title": item.title,
                    "published_at": item.published_at,
                    "actions": {},
                }

        llm = llm_factory(llm_config)

        for video_id, video in state["videos"].items():
            if not _needs_processing(video):
                continue

            source = source_by_playlist.get(video["playlist_id"])
            if source is None:
                continue

            agent_runner(
                llm=llm,
                policy_text=source.policy_text,
                video={
                    "video_id": video_id,
                    "title": video["title"],
                    "published_at": video["published_at"],
                },
                actions_state=video["actions"],
                output_dir=source.output_dir / video_id,
                dry_run=dry_run,
                spotify_playlist_id=source.spotify_playlist_id,
                spotify_overrides=overrides,
            )

        save_state(state_path, state)

    return state
