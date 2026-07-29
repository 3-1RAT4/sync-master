import re
from dataclasses import dataclass
from pathlib import Path

_SUFFIX_RE = re.compile(r"^(.*)\[([^\]]*)\]$")

_FLAG_ACTIONS = {
    "!": ["download"],
    "@": ["spotify_sync"],
    "#": ["transcript", "summarize"],
}

_CANONICAL_ORDER = ["download", "transcript", "summarize", "spotify_sync"]


@dataclass(frozen=True)
class ParsedPlaylist:
    folder_path: Path
    leaf_name: str
    actions: list[str]


def parse_playlist_name(title: str) -> ParsedPlaylist | None:
    match = _SUFFIX_RE.match(title)
    if not match:
        return None

    path_part, flags = match.groups()

    actions: set[str] = set()
    for char in flags:
        actions.update(_FLAG_ACTIONS.get(char, []))

    if not actions:
        return None

    segments = path_part.split("-")
    leaf_name = segments[-1]

    return ParsedPlaylist(
        folder_path=Path(*segments),
        leaf_name=leaf_name,
        actions=[action for action in _CANONICAL_ORDER if action in actions],
    )
