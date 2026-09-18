import pytest

from sync_master.agent.orchestrator import make_action_tools, needs_processing, run_actions_for_video
from sync_master.tools.summarize import SummaryResult
from sync_master.tools.transcript import TranscriptResult
from sync_master.vault import VideoFolder, read_frontmatter


@pytest.fixture
def vf(tmp_path):
    folder = VideoFolder(tmp_path / "vault" / "1.My Video Title", "1.My Video Title")
    folder.folder.mkdir(parents=True)
    folder.note.write_text("---\nyoutube_id: v1\ntype: video\n---\n\n# My Video Title\n")
    return folder


def _fake_download(video_id, scratch_dir, title=None):
    scratch_dir.mkdir(parents=True, exist_ok=True)
    path = scratch_dir / "video.mp4"
    path.write_bytes(b"fake video bytes")
    return path


def _tools(tmp_path, vf, **kwargs):
    actions_state = kwargs.pop("actions_state", {})
    tools = make_action_tools(
        video_id="v1",
        scratch_dir=tmp_path / "scratch",
        actions_state=actions_state,
        dry_run=kwargs.pop("dry_run", False),
        call_log=kwargs.pop("call_log", []),
        vf=vf,
        video_title="My Video Title",
        **kwargs,
    )
    return {t.name: t for t in tools}, actions_state


def test_dry_run_logs_without_executing(tmp_path, vf):
    called = []
    log = []
    tools, state = _tools(tmp_path, vf, dry_run=True, call_log=log, download_fn=lambda *a, **k: called.append(a))

    assert tools["download"].func() == "[dry-run] would run download"
    assert called == [] and state == {}
    assert log == [{"tool": "download", "video_id": "v1"}]


def test_download_copies_the_scratch_file_into_the_vault(tmp_path, vf):
    tools, state = _tools(tmp_path, vf, download_fn=_fake_download)

    assert tools["download"].func() == "download completed"
    assert vf.video.read_bytes() == b"fake video bytes"
    assert (tmp_path / "scratch" / "video.mp4").exists()  # scratch copy kept for transcription
    assert state["download"]["status"] == "done" and "updated_at" in state["download"]


def test_transcript_lands_as_a_note_in_the_vault(tmp_path, vf):
    def fake_transcript(video_id, scratch_dir, title=None):
        assert title == "My Video Title"
        return TranscriptResult(text="[00:00:00] SPEAKER_00: hello", source="captions", segments=[])

    tools, state = _tools(tmp_path, vf, transcript_fn=fake_transcript)

    tools["transcript"].func()
    assert "**[00:00:00] Speaker 00:** hello" in vf.transcript.read_text()
    assert "youtube_id: v1" in vf.transcript.read_text()
    assert state["transcript"]["status"] == "done"


def test_summarize_reads_the_transcript_from_the_vault(tmp_path, vf):
    vf.transcript.write_text("---\ntype: transcript\n---\n\n# Transcript — x\n\n**[00:00:00] Speaker 00:** hello there\n")
    seen = []

    def fake_summarize(text, instructions):
        seen.append(text)
        return SummaryResult(content="**Summary**", llm_provider="deepseek", llm_model="deepseek-chat")

    tools, state = _tools(tmp_path, vf, summarize_fn=fake_summarize)

    tools["summarize"].func()
    assert seen == ["[00:00:00] SPEAKER_00: hello there"]
    assert vf.summary.read_text().endswith("**Summary**\n")
    assert state["summarize"]["status"] == "done"


def test_summarize_fails_cleanly_without_a_transcript(tmp_path, vf):
    tools, state = _tools(tmp_path, vf, summarize_fn=lambda *a: pytest.fail("must not be called"))

    assert tools["summarize"].func().startswith("summarize failed: No transcript in the vault")
    assert state["summarize"]["status"] == "failed" and "error" in state["summarize"]


def test_failed_action_records_the_error(tmp_path, vf):
    def boom(*a, **k):
        raise RuntimeError("HTTP 403 Forbidden")

    tools, state = _tools(tmp_path, vf, download_fn=boom)
    assert tools["download"].func() == "download failed: HTTP 403 Forbidden"
    assert state["download"] == {"status": "failed", "updated_at": state["download"]["updated_at"], "error": "HTTP 403 Forbidden"}


def test_spotify_sync_resolves_the_playlist_once_and_records_the_match_on_the_note(tmp_path, vf):
    added, resolved = [], []
    cache = {}
    tools, state = _tools(
        tmp_path, vf,
        search_track_fn=lambda q: "spotify:track:found",
        find_or_create_playlist_fn=lambda name: (resolved.append(name), "spotify:playlist:zzz")[1],
        add_to_playlist_fn=lambda pid, uri: added.append((pid, uri)),
        spotify_playlist_name="PARTY",
        spotify_playlist_cache=cache,
    )

    tools["spotify_sync"].func()
    tools["spotify_sync"].func()

    assert resolved == ["PARTY"]  # second call hits the cache
    assert cache == {"PARTY": "spotify:playlist:zzz"}
    assert added == [("spotify:playlist:zzz", "spotify:track:found")] * 2
    fm = read_frontmatter(vf.note)
    assert fm["spotify_track_uri"] == "spotify:track:found" and fm["spotify_matched_via"] == "search"
    assert state["spotify_sync"]["status"] == "done"


def test_spotify_sync_override_uri_skips_search(tmp_path, vf):
    tools, _ = _tools(
        tmp_path, vf,
        search_track_fn=lambda q: pytest.fail("search must not run"),
        add_to_playlist_fn=lambda pid, uri: None,
        spotify_playlist_name="PARTY", spotify_playlist_cache={"PARTY": "p"},
        spotify_overrides={"v1": "spotify:track:forced"},
    )
    tools["spotify_sync"].func()
    assert read_frontmatter(vf.note)["spotify_matched_via"] == "override"


def test_spotify_sync_no_match_is_recorded_as_such(tmp_path, vf):
    tools, state = _tools(tmp_path, vf, search_track_fn=lambda q: None, spotify_playlist_name="PARTY")
    assert tools["spotify_sync"].func() == "spotify_sync: no match found"
    assert state["spotify_sync"]["status"] == "no_match"


def test_needs_processing_lets_the_vault_override_the_ledger(tmp_path, vf):
    state = {"download": {"status": "done"}, "summarize": {"status": "done"}, "spotify_sync": {"status": "no_match"}}
    # Ledger says done, but nothing is in the folder.
    assert needs_processing(state, ["download"], vf)
    vf.video.write_bytes(b"x")
    assert not needs_processing(state, ["download"], vf)
    # no_match is final; failed and missing are not.
    assert not needs_processing(state, ["spotify_sync"], vf)
    assert needs_processing(state, ["transcript"], vf)
    assert needs_processing({"download": {"status": "failed"}}, ["download"], vf)
    # Without a folder to check, the ledger alone decides.
    assert not needs_processing(state, ["download"], None)


def test_run_actions_skips_finished_ones_and_runs_the_rest(tmp_path, vf):
    vf.video.write_bytes(b"already there")
    ran = []
    state = {"download": {"status": "done"}}

    run_actions_for_video(
        ["download", "transcript"], "v1", tmp_path / "scratch", state, vf=vf,
        download_fn=lambda *a, **k: ran.append("download"),
        transcript_fn=lambda *a, **k: (ran.append("transcript"), TranscriptResult("[00:00:00] SPEAKER_00: x", "captions", []))[1],
    )

    assert ran == ["transcript"]
    assert state["transcript"]["status"] == "done"
