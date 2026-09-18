from sync_master.bootstrap import (
    check_vault,
    check_external_tools,
    check_missing_credentials,
    crontab_line,
    scaffold_config_dir,
)


def test_scaffold_config_dir_creates_expected_structure(tmp_path):
    config_dir = tmp_path / "sync-master"

    scaffold_config_dir(config_dir)

    assert (config_dir / "logs").is_dir()
    assert not (config_dir / "state.json").exists()
    assert (config_dir / "spotify_overrides.json").exists()
    assert (config_dir / "credentials.env").exists()
    assert (config_dir / "llm.yaml").exists()
    assert (config_dir / "settings.yaml").exists()
    assert "DATABASE_URL" not in (config_dir / "credentials.env").read_text()
    assert "vault_dir:" in (config_dir / "settings.yaml").read_text()
    assert not (config_dir / "sources").exists()


def test_scaffold_config_dir_does_not_overwrite_existing_files(tmp_path):
    config_dir = tmp_path / "sync-master"
    config_dir.mkdir()
    (config_dir / "spotify_overrides.json").write_text('{"v1": "spotify:track:abc123"}')

    scaffold_config_dir(config_dir)

    assert (config_dir / "spotify_overrides.json").read_text() == '{"v1": "spotify:track:abc123"}'


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


def test_check_vault_requires_an_existing_obsidian_vault(tmp_path):
    assert check_vault(None) == "vault_dir is not set in settings.yaml"
    assert "does not exist" in check_vault(str(tmp_path / "nope"))
    assert "no .obsidian/" in check_vault(str(tmp_path))
    (tmp_path / ".obsidian").mkdir()
    assert check_vault(str(tmp_path)) is None


def test_check_external_tools_reports_availability():
    result = check_external_tools(which_fn=lambda name: None)
    assert result == {"ffmpeg": False, "deno": False}
    result = check_external_tools(which_fn=lambda name: "/usr/bin/" + name)
    assert result == {"ffmpeg": True, "deno": True}


def test_crontab_line_uses_given_interval():
    line = crontab_line(interval_minutes=15)

    assert line == "*/15 * * * * sync-master run"
