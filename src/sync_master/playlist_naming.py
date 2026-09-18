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


def derive_folder_segments(title: str) -> list[str]:
    """The folder path a playlist name encodes, for *every* playlist.

    parse_playlist_name only recognises flagged playlists, because it decides
    what the pipeline does. This is purely structural - strip a trailing
    [...] suffix if there is one, split on "-" - and mirrors the web UI's
    taxonomy.ts:derivePathSegments, so both sides place a playlist in the
    same folder. A title with no dashes becomes a single top-level folder.
    """
    match = _SUFFIX_RE.match(title)
    path_part = match.group(1) if match else title
    return [segment for segment in path_part.split("-") if segment]


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
