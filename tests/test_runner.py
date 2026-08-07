from sync_master.runner import perform_run
from sync_master.sources.youtube import PlaylistInfo, VideoItem


def _write_settings(config_dir):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "settings.yaml").write_text(f"output_base_dir: {config_dir / 'output'}\n")


def test_perform_run_skips_playlists_with_no_recognized_flags(tmp_path):
    _write_settings(tmp_path)

    def fake_fetch_playlists(client):
        return [PlaylistInfo(playlist_id="PL_UNTRACKED", title="Favoritos")]

    def fake_fetch_items(playlist_id, youtube_client=None):
        raise AssertionError("must not fetch items for an untracked playlist")

    state = perform_run(
        tmp_path,
        dry_run=False,
        fetch_playlists_fn=fake_fetch_playlists,
        fetch_items_fn=fake_fetch_items,
        youtube_client_factory=lambda: "fake-client",
        action_runner=lambda **kwargs: None,
    )

    assert state["videos"] == {}


def test_perform_run_adds_newly_fetched_videos_from_flagged_playlist(tmp_path):
    _write_settings(tmp_path)

    def fake_fetch_playlists(client):
        return [PlaylistInfo(playlist_id="PL123", title="HUMAN-MUSIC-PARTY[!@]")]

    def fake_fetch_items(playlist_id, youtube_client=None):
        return [VideoItem(video_id="v1", title="Ep 1", published_at="2026-01-01", playlist_id=playlist_id)]

    calls = []

    def fake_action_runner(**kwargs):
        calls.append(kwargs)
        kwargs["actions_state"]["download"] = {"status": "done"}

    state = perform_run(
        tmp_path,
        dry_run=False,
        fetch_playlists_fn=fake_fetch_playlists,
        fetch_items_fn=fake_fetch_items,
        youtube_client_factory=lambda: "fake-client",
        action_runner=fake_action_runner,
    )

    assert "v1" in state["videos"]
    assert len(calls) == 1
    assert calls[0]["action_names"] == ["download", "spotify_sync"]
    assert calls[0]["spotify_playlist_name"] == "PARTY"
    assert str(calls[0]["output_dir"]).endswith("output/HUMAN/MUSIC/PARTY/v1")


def test_perform_run_appends_summary_entry_to_run_log(tmp_path):
    _write_settings(tmp_path)

    def fake_fetch_playlists(client):
        return [PlaylistInfo(playlist_id="PL123", title="HUMAN-MUSIC-PARTY[!@]")]

    def fake_fetch_items(playlist_id, youtube_client=None):
        return [VideoItem(video_id="v1", title="Ep 1", published_at="2026-01-01", playlist_id=playlist_id)]

    def fake_action_runner(**kwargs):
        kwargs["call_log"].append({"tool": "download", "video_id": "v1"})

    run_log = []
    perform_run(
        tmp_path,
        dry_run=True,
        fetch_playlists_fn=fake_fetch_playlists,
        fetch_items_fn=fake_fetch_items,
        youtube_client_factory=lambda: "fake-client",
        action_runner=fake_action_runner,
        run_log=run_log,
    )

    assert run_log == [
        {
            "video_id": "v1",
            "title": "Ep 1",
            "folder_path": "HUMAN/MUSIC/PARTY",
            "actions": ["download", "spotify_sync"],
            "call_log": [{"tool": "download", "video_id": "v1"}],
        }
    ]


def test_perform_run_skips_videos_with_no_failed_actions_and_already_processed(tmp_path):
    _write_settings(tmp_path)
    (tmp_path / "state.json").write_text(
        '{"videos": {"v1": {"playlist_id": "PL123", "title": "Ep 1", '
        '"published_at": "2026-01-01", "actions": {"download": {"status": "done"}}}}}'
    )

    def fake_fetch_playlists(client):
        return [PlaylistInfo(playlist_id="PL123", title="HUMAN-MUSIC-PARTY[!]")]

    def fake_fetch_items(playlist_id, youtube_client=None):
        return [VideoItem(video_id="v1", title="Ep 1", published_at="2026-01-01", playlist_id=playlist_id)]

    calls = []

    perform_run(
        tmp_path,
        dry_run=False,
        fetch_playlists_fn=fake_fetch_playlists,
        fetch_items_fn=fake_fetch_items,
        youtube_client_factory=lambda: "fake-client",
        action_runner=lambda **kwargs: calls.append(kwargs),
    )

    assert calls == []


def test_perform_run_reprocesses_video_missing_a_currently_required_action(tmp_path):
    _write_settings(tmp_path)
    (tmp_path / "state.json").write_text(
        '{"videos": {"v1": {"playlist_id": "PL123", "title": "Ep 1", '
        '"published_at": "2026-01-01", "actions": {"download": {"status": "done"}}}}}'
    )

    def fake_fetch_playlists(client):
        return [PlaylistInfo(playlist_id="PL123", title="HUMAN-MUSIC-PARTY[!@]")]

    def fake_fetch_items(playlist_id, youtube_client=None):
        return [VideoItem(video_id="v1", title="Ep 1", published_at="2026-01-01", playlist_id=playlist_id)]

    calls = []

    perform_run(
        tmp_path,
        dry_run=False,
        fetch_playlists_fn=fake_fetch_playlists,
        fetch_items_fn=fake_fetch_items,
        youtube_client_factory=lambda: "fake-client",
        action_runner=lambda **kwargs: calls.append(kwargs),
    )

    assert len(calls) == 1
    assert calls[0]["action_names"] == ["download", "spotify_sync"]


def test_perform_run_skips_video_with_no_match_status_for_required_action(tmp_path):
    _write_settings(tmp_path)
    (tmp_path / "state.json").write_text(
        '{"videos": {"v1": {"playlist_id": "PL123", "title": "Ep 1", '
        '"published_at": "2026-01-01", "actions": {"spotify_sync": {"status": "no_match"}}}}}'
    )

    def fake_fetch_playlists(client):
        return [PlaylistInfo(playlist_id="PL123", title="HUMAN-MUSIC-PARTY[@]")]

    def fake_fetch_items(playlist_id, youtube_client=None):
        return [VideoItem(video_id="v1", title="Ep 1", published_at="2026-01-01", playlist_id=playlist_id)]

    calls = []

    perform_run(
        tmp_path,
        dry_run=False,
        fetch_playlists_fn=fake_fetch_playlists,
        fetch_items_fn=fake_fetch_items,
        youtube_client_factory=lambda: "fake-client",
        action_runner=lambda **kwargs: calls.append(kwargs),
    )

    assert calls == []


def test_perform_run_retries_videos_with_failed_actions(tmp_path):
    _write_settings(tmp_path)
    (tmp_path / "state.json").write_text(
        '{"videos": {"v1": {"playlist_id": "PL123", "title": "Ep 1", '
        '"published_at": "2026-01-01", "actions": {"download": {"status": "failed"}}}}}'
    )

    def fake_fetch_playlists(client):
        return [PlaylistInfo(playlist_id="PL123", title="HUMAN-MUSIC-PARTY[!]")]

    def fake_fetch_items(playlist_id, youtube_client=None):
        return [VideoItem(video_id="v1", title="Ep 1", published_at="2026-01-01", playlist_id=playlist_id)]

    calls = []

    perform_run(
        tmp_path,
        dry_run=False,
        fetch_playlists_fn=fake_fetch_playlists,
        fetch_items_fn=fake_fetch_items,
        youtube_client_factory=lambda: "fake-client",
        action_runner=lambda **kwargs: calls.append(kwargs),
    )

    assert len(calls) == 1


def test_perform_run_persists_state_to_disk(tmp_path):
    _write_settings(tmp_path)

    def fake_fetch_playlists(client):
        return [PlaylistInfo(playlist_id="PL123", title="HUMAN-MUSIC-PARTY[!]")]

    def fake_fetch_items(playlist_id, youtube_client=None):
        return [VideoItem(video_id="v1", title="Ep 1", published_at="2026-01-01", playlist_id=playlist_id)]

    perform_run(
        tmp_path,
        dry_run=False,
        fetch_playlists_fn=fake_fetch_playlists,
        fetch_items_fn=fake_fetch_items,
        youtube_client_factory=lambda: "fake-client",
        action_runner=lambda **kwargs: None,
    )

    assert (tmp_path / "state.json").exists()
