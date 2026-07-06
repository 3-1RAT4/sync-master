import json
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class SourceConfig:
    name: str
    playlist_id: str
    output_dir: Path
    policy_text: str
    spotify_playlist_id: str | None = None


def parse_source_file(path: Path) -> SourceConfig:
    raw = path.read_text()
    _, frontmatter_raw, body = raw.split("---", 2)
    frontmatter = yaml.safe_load(frontmatter_raw)

    return SourceConfig(
        name=frontmatter["name"],
        playlist_id=frontmatter["playlist_id"],
        output_dir=Path(frontmatter["output_dir"]),
        policy_text=body.strip(),
        spotify_playlist_id=frontmatter.get("spotify_playlist_id"),
    )


def load_sources(sources_dir: Path) -> list[SourceConfig]:
    return [parse_source_file(path) for path in sorted(sources_dir.glob("*.md"))]


def load_llm_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def load_spotify_overrides(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())
