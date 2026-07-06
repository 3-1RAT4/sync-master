from sync_master.agent.orchestrator import build_prompt, make_action_tools


def _spotify_tool(tmp_path, **kwargs):
    actions_state = kwargs.pop("actions_state", {})
    tools = make_action_tools(
        video_id="v1",
        output_dir=tmp_path,
        actions_state=actions_state,
        dry_run=False,
        call_log=[],
        video_title="My Video Title",
        **kwargs,
    )
    tool = next(t for t in tools if t.name == "spotify_sync")
    return tool, actions_state


def test_build_prompt_includes_policy_video_and_action_state():
    prompt = build_prompt(
        policy_text="Summarize this and sync to Spotify.",
        video={"video_id": "v1", "title": "My Video", "published_at": "2026-01-01"},
        actions_state={"transcript": {"status": "pending"}},
    )

    assert "Summarize this and sync to Spotify." in prompt
    assert "My Video" in prompt
    assert "v1" in prompt
    assert "transcript" in prompt
    assert "pending" in prompt


def test_make_action_tools_dry_run_logs_without_executing_real_action(tmp_path):
    call_log = []
    actions_state = {}

    def real_download(video_id, output_dir):
        raise AssertionError("real action must not run in dry-run mode")

    tools = make_action_tools(
        video_id="v1",
        output_dir=tmp_path,
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

    def real_download(video_id, output_dir):
        executed.append((video_id, output_dir))

    tools = make_action_tools(
        video_id="v1",
        output_dir=tmp_path,
        actions_state=actions_state,
        dry_run=False,
        call_log=call_log,
        download_fn=real_download,
    )
    download_tool = next(t for t in tools if t.name == "download")

    download_tool.func()

    assert executed == [("v1", tmp_path)]
    assert actions_state["download"]["status"] == "done"


def test_make_action_tools_marks_failed_status_on_exception(tmp_path):
    actions_state = {}

    def failing_download(video_id, output_dir):
        raise RuntimeError("network error")

    tools = make_action_tools(
        video_id="v1",
        output_dir=tmp_path,
        actions_state=actions_state,
        dry_run=False,
        call_log=[],
        download_fn=failing_download,
    )
    download_tool = next(t for t in tools if t.name == "download")

    download_tool.func()

    assert actions_state["download"]["status"] == "failed"
    assert "network error" in actions_state["download"]["error"]


def test_spotify_sync_uses_search_result_when_no_override(tmp_path):
    added = []

    def fake_search(query):
        assert query == "My Video Title"
        return "spotify:track:found"

    def fake_add(playlist_id, uri):
        added.append((playlist_id, uri))

    tool, actions_state = _spotify_tool(
        tmp_path,
        search_track_fn=fake_search,
        add_to_playlist_fn=fake_add,
        spotify_playlist_id="spotify:playlist:zzz",
    )

    tool.func()

    assert added == [("spotify:playlist:zzz", "spotify:track:found")]
    assert actions_state["spotify_sync"]["status"] == "done"


def test_spotify_sync_marks_no_match_when_search_finds_nothing(tmp_path):
    added = []

    tool, actions_state = _spotify_tool(
        tmp_path,
        search_track_fn=lambda query: None,
        add_to_playlist_fn=lambda playlist_id, uri: added.append((playlist_id, uri)),
        spotify_playlist_id="spotify:playlist:zzz",
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
        spotify_playlist_id="spotify:playlist:zzz",
        spotify_overrides={"v1": "spotify:track:override"},
    )

    tool.func()

    assert added == [("spotify:playlist:zzz", "spotify:track:override")]
    assert actions_state["spotify_sync"]["status"] == "done"


def test_spotify_sync_uses_corrected_search_text_override(tmp_path):
    received_queries = []

    def fake_search(query):
        received_queries.append(query)
        return "spotify:track:corrected"

    tool, actions_state = _spotify_tool(
        tmp_path,
        search_track_fn=fake_search,
        add_to_playlist_fn=lambda playlist_id, uri: None,
        spotify_playlist_id="spotify:playlist:zzz",
        spotify_overrides={"v1": "corrected search text"},
    )

    tool.func()

    assert received_queries == ["corrected search text"]
    assert actions_state["spotify_sync"]["status"] == "done"
