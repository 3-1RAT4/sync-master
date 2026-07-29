import json
from pathlib import Path

import yaml


def load_llm_config(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def load_settings(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def load_spotify_overrides(path: Path) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text())
