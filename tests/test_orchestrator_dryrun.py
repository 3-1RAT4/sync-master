from sync_master.agent.orchestrator import make_action_tools, run_actions_for_video
from sync_master.tools.summarize import SummaryResult
from sync_master.tools.transcript import TranscriptResult


def _noop(*args, **kwargs):
    pass


def _fake_download(video_id, scratch_dir, title=None):
    path = scratch_dir / "video.mp4"
    scratch_dir.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fake video bytes")
    return path


def _spotify_tool(tmp_path, **kwargs):
    actions_state = kwargs.pop("actions_state", {})
    find_or_create_playlist_fn = kwargs.pop(
        "find_or_create_playlist_fn", lambda name: "spotify:playlist:zzz"
    )
    kwargs.setdefault("save_spotify_sync_fn", _noop)
    tools = make_action_tools(
        video_id="v1",
        scratch_dir=tmp_path,
        actions_state=actions_state,
        dry_run=False,
        call_log=[],
        video_title="My Video Title",
        find_or_create_playlist_fn=find_or_create_playlist_fn,
        **kwargs,
    )
    tool = next(t for t in tools if t.name == "spotify_sync")
    return tool, actions_state


def test_make_action_tools_dry_run_logs_without_executing_real_action(tmp_path):
    call_log = []
    actions_state = {}

    def real_download(video_id, scratch_dir, title=None):
        raise AssertionError("real action must not run in dry-run mode")

    tools = make_action_tools(
        video_id="v1",
        scratch_dir=tmp_path,
        actions_state=actions_state,
        dry_run=True,
        call_log=call_log,
        download_fn=real_download,
    )
    download_tool = next(t for t in tools if t.name == "download")

    download_tool.func()

    assert call_log == [{"tool": "download", "video_id": "v1"}]
    assert actions_state == {}


def test_make_action_tools_real_run_executes_and_updates_state(tmp_path):
    call_log = []
    actions_state = {}
    executed = []
    saved_files = []

    def real_download(video_id, scratch_dir, title=None):
        executed.append((video_id, scratch_dir, title))
        return _fake_download(video_id, scratch_dir, title)

    tools = make_action_tools(
        video_id="v1",
        scratch_dir=tmp_path,
        actions_state=actions_state,
        dry_run=False,
        call_log=call_log,
        download_fn=real_download,
        save_video_file_fn=lambda *a, **kw: saved_files.append((a, kw)),
    )
    download_tool = next(t for t in tools if t.name == "download")

    download_tool.func()

    assert [(video_id, scratch_dir, title) for video_id, scratch_dir, title in executed] == [
        ("v1", tmp_path, None)
    ]
    assert actions_state["download"]["status"] == "done"
    assert len(saved_files) == 1


def test_make_action_tools_passes_video_title_through_to_download_fn(tmp_path):
    captured = []

    def real_download(video_id, scratch_dir, title=None):
        captured.append(title)
        return _fake_download(video_id, scratch_dir, title)

    tools = make_action_tools(
        video_id="v1",
        scratch_dir=tmp_path,
        actions_state={},
        dry_run=False,
        call_log=[],
        download_fn=real_download,
        video_title="My Video Title",
        save_video_file_fn=_noop,
    )
    download_tool = next(t for t in tools if t.name == "download")

    download_tool.func()

    assert captured == ["My Video Title"]


def test_make_action_tools_passes_video_title_through_to_transcript_fn(tmp_path):
    captured = []

    def real_transcript(video_id, scratch_dir, title=None):
        captured.append(title)
        return TranscriptResult(text="body", source="captions", segments=[])

    tools = make_action_tools(
        video_id="v1",
        scratch_dir=tmp_path,
        actions_state={},
        dry_run=False,
        call_log=[],
        transcript_fn=real_transcript,
        video_title="My Video Title",
        save_transcript_fn=_noop,
    )
    transcript_tool = next(t for t in tools if t.name == "transcript")

    transcript_tool.func()

    assert captured == ["My Video Title"]


def test_summarize_action_reads_stored_transcript_text(tmp_path):
    received = {}

    def fake_get_transcript_text(session, video_id):
        return "the transcript body"

    def fake_summarize(transcript_text, instructions):
        received["transcript_text"] = transcript_text
        return SummaryResult(content="a summary", llm_provider="deepseek", llm_model="deepseek-chat")

    tools = make_action_tools(
        video_id="v1",
        scratch_dir=tmp_path,
        actions_state={},
        dry_run=False,
        call_log=[],
        summarize_fn=fake_summarize,
        get_transcript_text_fn=fake_get_transcript_text,
        video_title="My Video Title",
        save_summary_fn=_noop,
    )
    summarize_tool = next(t for t in tools if t.name == "summarize")

    summarize_tool.func()

    assert received["transcript_text"] == "the transcript body"


def test_summarize_action_raises_when_no_transcript_stored(tmp_path):
    actions_state = {}

    tools = make_action_tools(
        video_id="v1",
        scratch_dir=tmp_path,
        actions_state=actions_state,
        dry_run=False,
        call_log=[],
        get_transcript_text_fn=lambda session, video_id: None,
    )
    summarize_tool = next(t for t in tools if t.name == "summarize")

    summarize_tool.func()

    assert actions_state["summarize"]["status"] == "failed"
    assert "transcript" in actions_state["summarize"]["error"]


def test_make_action_tools_marks_failed_status_on_exception(tmp_path):
    actions_state = {}

    def failing_download(video_id, scratch_dir, title=None):
        raise RuntimeError("network error")

    tools = make_action_tools(
        video_id="v1",
        scratch_dir=tmp_path,
        actions_state=actions_state,
        dry_run=False,
        call_log=[],
        download_fn=failing_download,
    )
    download_tool = next(t for t in tools if t.name == "download")

    download_tool.func()

    assert actions_state["download"]["status"] == "failed"
    assert "network error" in actions_state["download"]["error"]


def test_spotify_sync_resolves_playlist_id_by_name_then_adds_track(tmp_path):
    added = []
    resolved_names = []
    saved_syncs = []

    def fake_search(query):
        assert query == "My Video Title"
        return "spotify:track:found"

    def fake_find_or_create(name):
        resolved_names.append(name)
        return "spotify:playlist:zzz"

    tool, actions_state = _spotify_tool(
        tmp_path,
        search_track_fn=fake_search,
        add_to_playlist_fn=lambda playlist_id, uri: added.append((playlist_id, uri)),
        spotify_playlist_name="PARTY",
        find_or_create_playlist_fn=fake_find_or_create,
        save_spotify_sync_fn=lambda *a, **kw: saved_syncs.append((a, kw)),
    )

    tool.func()

    assert resolved_names == ["PARTY"]
    assert added == [("spotify:playlist:zzz", "spotify:track:found")]
    assert actions_state["spotify_sync"]["status"] == "done"
    assert len(saved_syncs) == 1


def test_spotify_sync_marks_no_match_when_search_finds_nothing(tmp_path):
    added = []

    tool, actions_state = _spotify_tool(
        tmp_path,
        search_track_fn=lambda query: None,
        add_to_playlist_fn=lambda playlist_id, uri: added.append((playlist_id, uri)),
        spotify_playlist_name="PARTY",
    )

    tool.func()

    assert added == []
    assert actions_state["spotify_sync"]["status"] == "no_match"


def test_spotify_sync_uses_direct_uri_override_without_searching(tmp_path):
    added = []

    def fake_search(query):
        raise AssertionError("should not search when a direct URI override is given")

    tool, actions_state = _spotify_tool(
        tmp_path,
        search_track_fn=fake_search,
        add_to_playlist_fn=lambda playlist_id, uri: added.append((playlist_id, uri)),
        spotify_playlist_name="PARTY",
        spotify_overrides={"v1": "spotify:track:override"},
    )

    tool.func()

    assert added == [("spotify:playlist:zzz", "spotify:track:override")]
    assert actions_state["spotify_sync"]["status"] == "done"


def test_spotify_sync_uses_corrected_search_text_override(tmp_path):
    received_queries = []

    tool, actions_state = _spotify_tool(
        tmp_path,
        search_track_fn=lambda query: received_queries.append(query) or "spotify:track:corrected",
        add_to_playlist_fn=lambda playlist_id, uri: None,
        spotify_playlist_name="PARTY",
        spotify_overrides={"v1": "corrected search text"},
    )

    tool.func()

    assert received_queries == ["corrected search text"]
    assert actions_state["spotify_sync"]["status"] == "done"


def test_spotify_sync_records_track_id_extracted_from_uri(tmp_path):
    saved = {}

    def fake_save_spotify_sync(session, video_id, spotify_track_id, spotify_track_uri, spotify_playlist_id, matched_via):
        saved["track_id"] = spotify_track_id
        saved["track_uri"] = spotify_track_uri
        saved["matched_via"] = matched_via

    tool, _ = _spotify_tool(
        tmp_path,
        search_track_fn=lambda query: "spotify:track:abc123",
        add_to_playlist_fn=lambda playlist_id, uri: None,
        spotify_playlist_name="PARTY",
        save_spotify_sync_fn=fake_save_spotify_sync,
    )

    tool.func()

    assert saved == {"track_id": "abc123", "track_uri": "spotify:track:abc123", "matched_via": "search"}


def test_run_actions_for_video_runs_only_the_given_actions_in_canonical_order(tmp_path):
    executed = []

    tools_called = make_action_tools(
        video_id="v1",
        scratch_dir=tmp_path,
        actions_state={},
        dry_run=False,
        call_log=[],
    )
    assert {t.name for t in tools_called} == {"download", "transcript", "summarize", "spotify_sync"}

    def fake_download(video_id, scratch_dir, title=None):
        executed.append("download")
        return _fake_download(video_id, scratch_dir, title)

    def fake_transcript(video_id, scratch_dir, title=None):
        executed.append("transcript")
        return TranscriptResult(text="body", source="captions", segments=[])

    actions_state = {}
    run_actions_for_video(
        action_names=["download", "transcript"],
        video_id="v1",
        scratch_dir=tmp_path,
        actions_state=actions_state,
        dry_run=False,
        download_fn=fake_download,
        transcript_fn=fake_transcript,
        save_video_file_fn=_noop,
        save_transcript_fn=_noop,
    )

    assert executed == ["download", "transcript"]
    assert actions_state["download"]["status"] == "done"
    assert actions_state["transcript"]["status"] == "done"
    assert "summarize" not in actions_state
    assert "spotify_sync" not in actions_state


def test_run_actions_for_video_skips_actions_already_done(tmp_path):
    executed = []

    def fake_download(video_id, scratch_dir, title=None):
        executed.append("download")

    actions_state = {"download": {"status": "done"}}
    run_actions_for_video(
        action_names=["download"],
        video_id="v1",
        scratch_dir=tmp_path,
        actions_state=actions_state,
        dry_run=False,
        download_fn=fake_download,
    )

    assert executed == []


def test_run_actions_for_video_dry_run_logs_without_executing(tmp_path):
    def real_download(video_id, scratch_dir, title=None):
        raise AssertionError("must not run in dry-run mode")

    call_log = []
    run_actions_for_video(
        action_names=["download"],
        video_id="v1",
        scratch_dir=tmp_path,
        actions_state={},
        dry_run=True,
        call_log=call_log,
        download_fn=real_download,
    )

    assert call_log == [{"tool": "download", "video_id": "v1"}]
