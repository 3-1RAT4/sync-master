from pathlib import Path

from sync_master.config import (
    SourceConfig,
    load_llm_config,
    load_sources,
    load_spotify_overrides,
    parse_source_file,
)

SOURCE_MD = """---
name: my-podcast
playlist_id: PLyyyyyyyyyyyy
output_dir: ./output/my-podcast
---

This is my podcast feed. Summarize each episode in 3 paragraphs.
"""


def test_parse_source_file_extracts_frontmatter_and_policy_body(tmp_path):
    source_path = tmp_path / "my-podcast.md"
    source_path.write_text(SOURCE_MD)

    config = parse_source_file(source_path)

    assert config == SourceConfig(
        name="my-podcast",
        playlist_id="PLyyyyyyyyyyyy",
        output_dir=Path("./output/my-podcast"),
        policy_text="This is my podcast feed. Summarize each episode in 3 paragraphs.",
    )


def test_load_sources_parses_every_markdown_file_in_directory(tmp_path):
    (tmp_path / "a.md").write_text(SOURCE_MD)
    other = SOURCE_MD.replace("my-podcast", "tech-talks").replace(
        "PLyyyyyyyyyyyy", "PLxxxxxxxxxxxx"
    )
    (tmp_path / "b.md").write_text(other)

    configs = load_sources(tmp_path)

    assert {c.name for c in configs} == {"my-podcast", "tech-talks"}


def test_load_llm_config_reads_yaml_file(tmp_path):
    llm_path = tmp_path / "llm.yaml"
    llm_path.write_text("provider: deepseek\nmodel: deepseek-chat\nbase_url: https://api.deepseek.com\n")

    config = load_llm_config(llm_path)

    assert config == {
        "provider": "deepseek",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com",
    }


def test_parse_source_file_reads_optional_spotify_playlist_id(tmp_path):
    source_path = tmp_path / "my-podcast.md"
    source_path.write_text(
        SOURCE_MD.replace(
            "output_dir: ./output/my-podcast",
            "output_dir: ./output/my-podcast\nspotify_playlist_id: spotify:playlist:zzz",
        )
    )

    config = parse_source_file(source_path)

    assert config.spotify_playlist_id == "spotify:playlist:zzz"


def test_parse_source_file_spotify_playlist_id_defaults_to_none(tmp_path):
    source_path = tmp_path / "my-podcast.md"
    source_path.write_text(SOURCE_MD)

    config = parse_source_file(source_path)

    assert config.spotify_playlist_id is None


def test_load_spotify_overrides_returns_empty_dict_when_file_missing(tmp_path):
    overrides = load_spotify_overrides(tmp_path / "spotify_overrides.json")

    assert overrides == {}


def test_load_spotify_overrides_parses_existing_file(tmp_path):
    path = tmp_path / "spotify_overrides.json"
    path.write_text('{"v1": "spotify:track:abc123"}')

    overrides = load_spotify_overrides(path)

    assert overrides == {"v1": "spotify:track:abc123"}
