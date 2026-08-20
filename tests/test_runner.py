import contextlib

import pytest

from sync_master.db.repository import LockHeldError
from sync_master.runner import perform_run
from sync_master.sources.youtube import PlaylistInfo, VideoItem


class FakeRepo:
    """In-memory stand-in for db.repository, so runner tests stay fast and
    don't need a real Postgres connection - only tests/db/test_repository.py
    exercises the real repository functions against Postgres."""

    def __init__(self):
        self.playlists: dict = {}
        self.state: dict = {"videos": {}}
        self.known_video_ids: set = set()

    def upsert_playlist(self, session, youtube_playlist_id, title, folder_path, leaf_name, actions):
        self.playlists[youtube_playlist_id] = {
            "title": title,
            "folder_path": folder_path,
            "leaf_name": leaf_name,
            "actions": actions,
        }

    def load_state(self, session):
        return self.state

    def save_state(self, session, data):
        self.state = data

    def ensure_video_row(self, session, youtube_video_id):
        self.known_video_ids.add(youtube_video_id)

    def seed_video(self, video_id, playlist_id, title, published_at, actions=None):
        self.state["videos"][video_id] = {
            "playlist_id": playlist_id,
            "title": title,
            "published_at": published_at,
            "actions": {name: {"status": status} for name, status in (actions or {}).items()},
        }
        self.known_video_ids.add(video_id)

    @contextlib.contextmanager
    def acquire_run_lock(self, session):
        yield


def _write_settings(config_dir):
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "settings.yaml").write_text(f"output_base_dir: {config_dir / 'output'}\n")


class _FakeSession:
    def close(self):
        pass


def _run(tmp_path, repo, **kwargs):
    _write_settings(tmp_path)
    kwargs.setdefault("session_factory", _FakeSession)
    kwargs.setdefault("acquire_run_lock", repo.acquire_run_lock)
    kwargs.setdefault("upsert_playlist_fn", repo.upsert_playlist)
    kwargs.setdefault("load_state_fn", repo.load_state)
    kwargs.setdefault("save_state_fn", repo.save_state)
    kwargs.setdefault("ensure_video_row_fn", repo.ensure_video_row)
    perform_run(tmp_path, **kwargs)


def test_perform_run_skips_playlists_with_no_recognized_flags(tmp_path):
    repo = FakeRepo()

    def fake_fetch_playlists(client):
        return [PlaylistInfo(playlist_id="PL_UNTRACKED", title="Favoritos")]

    def fake_fetch_items(playlist_id, youtube_client=None):
        raise AssertionError("must not fetch items for an untracked playlist")

    _run(
        tmp_path,
        repo,
        dry_run=False,
        fetch_playlists_fn=fake_fetch_playlists,
        fetch_items_fn=fake_fetch_items,
        youtube_client_factory=lambda: "fake-client",
        action_runner=lambda **kwargs: None,
    )

    assert repo.state["videos"] == {}


def test_perform_run_adds_newly_fetched_videos_from_flagged_playlist(tmp_path):
    repo = FakeRepo()

    def fake_fetch_playlists(client):
        return [PlaylistInfo(playlist_id="PL123", title="HUMAN-MUSIC-PARTY[!@]")]

    def fake_fetch_items(playlist_id, youtube_client=None):
        return [VideoItem(video_id="v1", title="Ep 1", published_at="2026-01-01", playlist_id=playlist_id)]

    calls = []

    def fake_action_runner(**kwargs):
        calls.append(kwargs)
        kwargs["actions_state"]["download"] = {"status": "done"}

    _run(
        tmp_path,
        repo,
        dry_run=False,
        fetch_playlists_fn=fake_fetch_playlists,
        fetch_items_fn=fake_fetch_items,
        youtube_client_factory=lambda: "fake-client",
        action_runner=fake_action_runner,
    )

    assert "v1" in repo.state["videos"]
    assert len(calls) == 1
    assert calls[0]["action_names"] == ["download", "spotify_sync"]
    assert calls[0]["spotify_playlist_name"] == "PARTY"
    assert str(calls[0]["scratch_dir"]).endswith("output/HUMAN/MUSIC/PARTY/v1")


def test_perform_run_appends_summary_entry_to_run_log(tmp_path):
    repo = FakeRepo()

    def fake_fetch_playlists(client):
        return [PlaylistInfo(playlist_id="PL123", title="HUMAN-MUSIC-PARTY[!@]")]

    def fake_fetch_items(playlist_id, youtube_client=None):
        return [VideoItem(video_id="v1", title="Ep 1", published_at="2026-01-01", playlist_id=playlist_id)]

    def fake_action_runner(**kwargs):
        kwargs["call_log"].append({"tool": "download", "video_id": "v1"})

    run_log = []
    _run(
        tmp_path,
        repo,
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


def test_perform_run_dry_run_does_not_save_state(tmp_path):
    repo = FakeRepo()
    saved = []
    repo.save_state = lambda session, data: saved.append(data)

    def fake_fetch_playlists(client):
        return [PlaylistInfo(playlist_id="PL123", title="HUMAN-MUSIC-PARTY[!@]")]

    def fake_fetch_items(playlist_id, youtube_client=None):
        return [VideoItem(video_id="v1", title="Ep 1", published_at="2026-01-01", playlist_id=playlist_id)]

    _run(
        tmp_path,
        repo,
        dry_run=True,
        fetch_playlists_fn=fake_fetch_playlists,
        fetch_items_fn=fake_fetch_items,
        youtube_client_factory=lambda: "fake-client",
        action_runner=lambda **kwargs: kwargs["call_log"].append({"tool": "download", "video_id": "v1"}),
    )

    assert saved == []


def test_perform_run_skips_videos_with_no_failed_actions_and_already_processed(tmp_path):
    repo = FakeRepo()
    repo.seed_video("v1", "PL123", "Ep 1", "2026-01-01", actions={"download": "done"})

    def fake_fetch_playlists(client):
        return [PlaylistInfo(playlist_id="PL123", title="HUMAN-MUSIC-PARTY[!]")]

    def fake_fetch_items(playlist_id, youtube_client=None):
        return [VideoItem(video_id="v1", title="Ep 1", published_at="2026-01-01", playlist_id=playlist_id)]

    calls = []

    _run(
        tmp_path,
        repo,
        dry_run=False,
        fetch_playlists_fn=fake_fetch_playlists,
        fetch_items_fn=fake_fetch_items,
        youtube_client_factory=lambda: "fake-client",
        action_runner=lambda **kwargs: calls.append(kwargs),
    )

    assert calls == []


def test_perform_run_reprocesses_video_missing_a_currently_required_action(tmp_path):
    repo = FakeRepo()
    repo.seed_video("v1", "PL123", "Ep 1", "2026-01-01", actions={"download": "done"})

    def fake_fetch_playlists(client):
        return [PlaylistInfo(playlist_id="PL123", title="HUMAN-MUSIC-PARTY[!@]")]

    def fake_fetch_items(playlist_id, youtube_client=None):
        return [VideoItem(video_id="v1", title="Ep 1", published_at="2026-01-01", playlist_id=playlist_id)]

    calls = []

    _run(
        tmp_path,
        repo,
        dry_run=False,
        fetch_playlists_fn=fake_fetch_playlists,
        fetch_items_fn=fake_fetch_items,
        youtube_client_factory=lambda: "fake-client",
        action_runner=lambda **kwargs: calls.append(kwargs),
    )

    assert len(calls) == 1
    assert calls[0]["action_names"] == ["download", "spotify_sync"]


def test_perform_run_skips_video_with_no_match_status_for_required_action(tmp_path):
    repo = FakeRepo()
    repo.seed_video("v1", "PL123", "Ep 1", "2026-01-01", actions={"spotify_sync": "no_match"})

    def fake_fetch_playlists(client):
        return [PlaylistInfo(playlist_id="PL123", title="HUMAN-MUSIC-PARTY[@]")]

    def fake_fetch_items(playlist_id, youtube_client=None):
        return [VideoItem(video_id="v1", title="Ep 1", published_at="2026-01-01", playlist_id=playlist_id)]

    calls = []

    _run(
        tmp_path,
        repo,
        dry_run=False,
        fetch_playlists_fn=fake_fetch_playlists,
        fetch_items_fn=fake_fetch_items,
        youtube_client_factory=lambda: "fake-client",
        action_runner=lambda **kwargs: calls.append(kwargs),
    )

    assert calls == []


def test_perform_run_retries_videos_with_failed_actions(tmp_path):
    repo = FakeRepo()
    repo.seed_video("v1", "PL123", "Ep 1", "2026-01-01", actions={"download": "failed"})

    def fake_fetch_playlists(client):
        return [PlaylistInfo(playlist_id="PL123", title="HUMAN-MUSIC-PARTY[!]")]

    def fake_fetch_items(playlist_id, youtube_client=None):
        return [VideoItem(video_id="v1", title="Ep 1", published_at="2026-01-01", playlist_id=playlist_id)]

    calls = []

    _run(
        tmp_path,
        repo,
        dry_run=False,
        fetch_playlists_fn=fake_fetch_playlists,
        fetch_items_fn=fake_fetch_items,
        youtube_client_factory=lambda: "fake-client",
        action_runner=lambda **kwargs: calls.append(kwargs),
    )

    assert len(calls) == 1


def test_perform_run_closes_the_session_even_when_lock_is_held(tmp_path):
    closed = []

    class FakeSession:
        def close(self):
            closed.append(True)

    @contextlib.contextmanager
    def held_lock(session):
        raise LockHeldError("already running")
        yield  # pragma: no cover

    _write_settings(tmp_path)
    with pytest.raises(LockHeldError):
        perform_run(
            tmp_path,
            session_factory=lambda: FakeSession(),
            acquire_run_lock=held_lock,
        )

    assert closed == [True]
