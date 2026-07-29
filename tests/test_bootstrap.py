from sync_master.bootstrap import (
    check_external_tools,
    check_missing_credentials,
    crontab_line,
    scaffold_config_dir,
)


def test_scaffold_config_dir_creates_expected_structure(tmp_path):
    config_dir = tmp_path / "sync-master"

    scaffold_config_dir(config_dir)

    assert (config_dir / "logs").is_dir()
    assert (config_dir / "state.json").exists()
    assert (config_dir / "spotify_overrides.json").exists()
    assert (config_dir / "credentials.env").exists()
    assert (config_dir / "llm.yaml").exists()
    assert (config_dir / "settings.yaml").exists()
    assert not (config_dir / "sources").exists()


def test_scaffold_config_dir_does_not_overwrite_existing_files(tmp_path):
    config_dir = tmp_path / "sync-master"
    config_dir.mkdir()
    (config_dir / "state.json").write_text('{"videos": {"v1": {}}}')

    scaffold_config_dir(config_dir)

    assert (config_dir / "state.json").read_text() == '{"videos": {"v1": {}}}'


def test_check_missing_credentials_reports_absent_keys(tmp_path, monkeypatch):
    for key in ["YOUTUBE_OAUTH_CLIENT_ID", "YOUTUBE_OAUTH_CLIENT_SECRET", "LLM_API_KEY",
                "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"]:
        monkeypatch.delenv(key, raising=False)
    credentials_path = tmp_path / "credentials.env"
    credentials_path.write_text("")

    missing = check_missing_credentials(credentials_path)

    assert set(missing) == {
        "YOUTUBE_OAUTH_CLIENT_ID",
        "YOUTUBE_OAUTH_CLIENT_SECRET",
        "LLM_API_KEY",
        "SPOTIFY_CLIENT_ID",
        "SPOTIFY_CLIENT_SECRET",
    }


def test_check_missing_credentials_excludes_keys_present_in_file(tmp_path, monkeypatch):
    for key in ["YOUTUBE_OAUTH_CLIENT_ID", "YOUTUBE_OAUTH_CLIENT_SECRET", "LLM_API_KEY",
                "SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET"]:
        monkeypatch.delenv(key, raising=False)
    credentials_path = tmp_path / "credentials.env"
    credentials_path.write_text(
        "YOUTUBE_OAUTH_CLIENT_ID=abc123\nYOUTUBE_OAUTH_CLIENT_SECRET=xyz789\n"
        "SPOTIFY_CLIENT_ID=abc123\nSPOTIFY_CLIENT_SECRET=xyz789\n"
    )

    missing = check_missing_credentials(credentials_path)

    assert missing == ["LLM_API_KEY"]


def test_check_external_tools_reports_availability():
    def fake_which(name):
        return "/usr/bin/yt-dlp" if name == "yt-dlp" else None

    result = check_external_tools(which_fn=fake_which)

    assert result == {"yt-dlp": True, "ffmpeg": False}


def test_crontab_line_uses_given_interval():
    line = crontab_line(interval_minutes=15)

    assert line == "*/15 * * * * sync-master run"
