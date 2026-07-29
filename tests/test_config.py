from sync_master.config import load_llm_config, load_settings, load_spotify_overrides


def test_load_llm_config_reads_yaml_file(tmp_path):
    llm_path = tmp_path / "llm.yaml"
    llm_path.write_text("provider: deepseek\nmodel: deepseek-chat\nbase_url: https://api.deepseek.com\n")

    config = load_llm_config(llm_path)

    assert config == {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
    }


def test_load_settings_reads_yaml_file(tmp_path):
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text("output_base_dir: /home/rodz/sync-master-output\n")

    settings = load_settings(settings_path)

    assert settings == {"output_base_dir": "/home/rodz/sync-master-output"}


def test_load_spotify_overrides_returns_empty_dict_when_file_missing(tmp_path):
    overrides = load_spotify_overrides(tmp_path / "spotify_overrides.json")

    assert overrides == {}


def test_load_spotify_overrides_parses_existing_file(tmp_path):
    path = tmp_path / "spotify_overrides.json"
    path.write_text('{"v1": "spotify:track:abc123"}')

    overrides = load_spotify_overrides(path)

    assert overrides == {"v1": "spotify:track:abc123"}
