from sync_master.runner import perform_run
from sync_master.sources.youtube import VideoItem


def _write_source(config_dir, name="my-podcast", playlist_id="PL123"):
    sources_dir = config_dir / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    (sources_dir / f"{name}.md").write_text(
        f"---\nname: {name}\nplaylist_id: {playlist_id}\n"
        f"output_dir: {config_dir / 'output' / name}\n---\n\nSummarize each episode.\n"
    )
    (config_dir / "llm.yaml").write_text("provider: fake\nmodel: fake-model\n")


def test_perform_run_adds_newly_fetched_videos_to_state(tmp_path):
    _write_source(tmp_path)

    def fake_fetch(playlist_id, api_key=None):
        return [VideoItem(video_id="v1", title="Ep 1", published_at="2026-01-01", playlist_id=playlist_id)]

    calls = []

    def fake_agent_runner(**kwargs):
        calls.append(kwargs)
        kwargs["actions_state"]["transcript"] = {"status": "done"}

    state = perform_run(
        tmp_path,
        dry_run=False,
        fetch_fn=fake_fetch,
        llm_factory=lambda cfg: "fake-llm",
        agent_runner=fake_agent_runner,
    )

    assert "v1" in state["videos"]
    assert state["videos"]["v1"]["title"] == "Ep 1"
    assert len(calls) == 1


def test_perform_run_skips_videos_with_no_failed_actions_and_already_processed(tmp_path):
    _write_source(tmp_path)
    state_path = tmp_path / "state.json"
    state_path.write_text(
        '{"videos": {"v1": {"playlist_id": "PL123", "title": "Ep 1", '
        '"published_at": "2026-01-01", "actions": {"transcript": {"status": "done"}}}}}'
    )

    def fake_fetch(playlist_id, api_key=None):
        return [VideoItem(video_id="v1", title="Ep 1", published_at="2026-01-01", playlist_id=playlist_id)]

    calls = []

    def fake_agent_runner(**kwargs):
        calls.append(kwargs)

    perform_run(
        tmp_path,
        dry_run=False,
        fetch_fn=fake_fetch,
        llm_factory=lambda cfg: "fake-llm",
        agent_runner=fake_agent_runner,
    )

    assert calls == []


def test_perform_run_retries_videos_with_failed_actions(tmp_path):
    _write_source(tmp_path)
    state_path = tmp_path / "state.json"
    state_path.write_text(
        '{"videos": {"v1": {"playlist_id": "PL123", "title": "Ep 1", '
        '"published_at": "2026-01-01", "actions": {"download": {"status": "failed"}}}}}'
    )

    def fake_fetch(playlist_id, api_key=None):
        return [VideoItem(video_id="v1", title="Ep 1", published_at="2026-01-01", playlist_id=playlist_id)]

    calls = []

    def fake_agent_runner(**kwargs):
        calls.append(kwargs)

    perform_run(
        tmp_path,
        dry_run=False,
        fetch_fn=fake_fetch,
        llm_factory=lambda cfg: "fake-llm",
        agent_runner=fake_agent_runner,
    )

    assert len(calls) == 1


def test_perform_run_persists_state_to_disk(tmp_path):
    _write_source(tmp_path)

    def fake_fetch(playlist_id, api_key=None):
        return [VideoItem(video_id="v1", title="Ep 1", published_at="2026-01-01", playlist_id=playlist_id)]

    perform_run(
        tmp_path,
        dry_run=False,
        fetch_fn=fake_fetch,
        llm_factory=lambda cfg: "fake-llm",
        agent_runner=lambda **kwargs: None,
    )

    assert (tmp_path / "state.json").exists()
