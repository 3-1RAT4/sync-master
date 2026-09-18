import json

import pytest

from sync_master.runner import perform_run
from sync_master.sources.youtube import PlaylistInfo, VideoItem
from sync_master.state import LockHeldError
from sync_master.vault import VAULT_SUBDIR, VideoFolder, read_frontmatter

FLAGGED = PlaylistInfo(playlist_id="PL1", title="HUMAN-PODCASTS[!#]")  # download, transcript, summarize
UNTRACKED = PlaylistInfo(playlist_id="PL2", title="HUMAN-MIND-TALKS")


def _item(video_id, title, playlist_id="PL1", position=0):
    return VideoItem(video_id=video_id, title=title, published_at="2026-01-01T00:00:00Z", playlist_id=playlist_id, position=position)


@pytest.fixture
def env(tmp_path):
    config = tmp_path / "config"
    config.mkdir()
    (config / "credentials.env").write_text("")
    vault = tmp_path / "vault"
    vault.mkdir()
    (config / "settings.yaml").write_text(f"output_base_dir: {tmp_path / 'scratch'}\nvault_dir: {vault}\n")
    return config, vault


def _run(env, playlists, items_by_playlist, **kwargs):
    config, vault = env
    calls = []

    def action_runner(**kw):
        calls.append(kw)
        if kw["dry_run"]:
            return
        for name in kw["action_names"]:
            kw["actions_state"][name] = {"status": "done"}
            # produce the file the vault-wins rule will look for
            out = {"download": kw["vf"].video, "transcript": kw["vf"].transcript, "summarize": kw["vf"].summary}.get(name)
            if out is not None:
                out.write_text("x")

    kwargs.setdefault("action_runner", action_runner)
    report = perform_run(
        config,
        fetch_playlists_fn=lambda client: playlists,
        fetch_items_fn=lambda pid, youtube_client=None: items_by_playlist.get(pid, []),
        youtube_client_factory=lambda: None,
        **kwargs,
    )
    return report, calls, vault / VAULT_SUBDIR, config


def test_every_playlist_is_catalogued_but_only_flagged_ones_dispatch(env):
    report, calls, root, config = _run(
        env, [FLAGGED, UNTRACKED], {"PL1": [_item("a", "Ep one")], "PL2": [_item("t", "A talk", "PL2")]}
    )

    assert (report.playlists, report.videos, report.created) == (2, 2, 2)
    assert (root / "HUMAN" / "PODCASTS" / "1.Ep one" / "1.Ep one.md").exists()
    assert (root / "HUMAN" / "MIND" / "TALKS" / "1.A talk" / "1.A talk.md").exists()
    assert [c["video_id"] for c in calls] == ["a"]
    assert calls[0]["action_names"] == ["download", "transcript", "summarize"]
    assert calls[0]["spotify_playlist_name"] == "PODCASTS"
    assert calls[0]["vf"] == VideoFolder(root / "HUMAN" / "PODCASTS" / "1.Ep one", "1.Ep one")

    state = json.loads((config / "state.json").read_text())
    assert set(state["videos"]) == {"a"}  # untracked videos never enter the ledger
    assert state["videos"]["a"]["actions"]["download"]["status"] == "done"
    assert report.processed[0]["folder_path"] == "HUMAN/PODCASTS"


def test_second_run_finds_folders_and_skips_finished_videos(env):
    items = {"PL1": [_item("a", "Ep one")]}
    _run(env, [FLAGGED], items)
    report, calls, root, _ = _run(env, [FLAGGED], items)

    assert (report.created, report.moved) == (0, 0)
    assert calls == []
    assert len(list((root / "HUMAN" / "PODCASTS").iterdir())) == 1


def test_reorder_on_youtube_renames_the_folder_instead_of_duplicating(env):
    _run(env, [FLAGGED], {"PL1": [_item("a", "Ep one", position=0), _item("b", "Ep two", position=1)]})
    report, _, root, _ = _run(env, [FLAGGED], {"PL1": [_item("b", "Ep two", position=0), _item("a", "Ep one", position=1)]})

    assert report.moved == 2 and report.created == 0
    assert sorted(p.name for p in (root / "HUMAN" / "PODCASTS").iterdir()) == ["1.Ep two", "2.Ep one"]
    assert read_frontmatter(root / "HUMAN" / "PODCASTS" / "2.Ep one" / "2.Ep one.md")["youtube_id"] == "a"


def test_a_deleted_output_is_regenerated_even_though_the_ledger_says_done(env):
    items = {"PL1": [_item("a", "Ep one")]}
    _, _, root, _ = _run(env, [FLAGGED], items)
    (root / "HUMAN" / "PODCASTS" / "1.Ep one" / "1.Ep one.summary.md").unlink()

    _, calls, _, _ = _run(env, [FLAGGED], items)

    assert [c["video_id"] for c in calls] == ["a"]


def test_failed_actions_are_retried_and_no_match_is_final(env):
    config, _ = env
    (config / "state.json").write_text(json.dumps({"videos": {
        "a": {"actions": {"download": {"status": "failed", "error": "403"}}},
    }}))
    _, calls, _, _ = _run(env, [FLAGGED], {"PL1": [_item("a", "Ep one")]})
    assert [c["video_id"] for c in calls] == ["a"]

    lofi = PlaylistInfo(playlist_id="PL3", title="MUSIC-LOFI[@]")  # spotify_sync only
    (config / "state.json").write_text(json.dumps({"videos": {"s": {"actions": {"spotify_sync": {"status": "no_match"}}}}}))
    _, calls, _, _ = _run(env, [lofi], {"PL3": [_item("s", "Song", "PL3")]})
    assert calls == []


def test_metadata_is_refreshed_without_reprocessing(env):
    items = {"PL1": [_item("a", "Old title")]}
    _run(env, [FLAGGED], items)
    _, calls, root, config = _run(env, [FLAGGED], {"PL1": [_item("a", "New title")]})

    assert calls == []
    state = json.loads((config / "state.json").read_text())
    assert state["videos"]["a"]["title"] == "New title"
    assert (root / "HUMAN" / "PODCASTS" / "1.New title").is_dir()


def test_dry_run_writes_nothing_and_reports_what_would_be_created(env):
    report, calls, root, config = _run(env, [FLAGGED], {"PL1": [_item("a", "Ep one")]}, dry_run=True)

    assert report.created == 1
    assert not root.exists()
    assert not (config / "state.json").exists()
    assert calls[0]["dry_run"] is True

    # A dry run must also count pending moves, not only creations.
    _run(env, [FLAGGED], {"PL1": [_item("a", "Ep one", position=0), _item("b", "Ep two", position=1)]})
    report, _, _, _ = _run(env, [FLAGGED], {"PL1": [_item("b", "Ep two", position=0), _item("a", "Ep one", position=1)]}, dry_run=True)
    assert (report.created, report.moved) == (0, 2)


def test_a_held_lock_refuses_to_run(env):
    config, _ = env
    (config / "state.json.lock").touch()
    with pytest.raises(LockHeldError):
        _run(env, [FLAGGED], {})


def test_a_video_listed_twice_in_a_playlist_keeps_its_first_position(env):
    items = {"PL1": [_item("a", "Ep one", position=0), _item("b", "Ep two", position=1), _item("a", "Ep one", position=2)]}
    report, _, root, _ = _run(env, [FLAGGED], items)
    assert (report.created, report.moved) == (2, 0)
    assert sorted(p.name for p in (root / "HUMAN" / "PODCASTS").iterdir()) == ["1.Ep one", "2.Ep two"]
    # and it stays put on the next run instead of flip-flopping
    report, _, _, _ = _run(env, [FLAGGED], items)
    assert (report.created, report.moved) == (0, 0)
