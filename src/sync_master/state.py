"""The action ledger: which actions have run for which video, and how they
went. Lives in ~/.config/sync-master/state.json - keyed by YouTube video id,
so it survives any reorganising of the vault. The vault itself holds the
content; this only records status, errors, and the Spotify playlist-name ->
id cache.

    {"videos": {"<youtube_id>": {"playlist_id", "title", "published_at",
                                 "actions": {"download": {"status", "updated_at", "error"?}, ...}}},
     "spotify_playlists": {"<name>": "<spotify playlist id>"}}
"""

import contextlib
import json
import os
from pathlib import Path


class LockHeldError(Exception):
    pass


def load_state(path: Path) -> dict:
    state = json.loads(path.read_text()) if path.exists() else {}
    state.setdefault("videos", {})
    state.setdefault("spotify_playlists", {})
    return state


def save_state(path: Path, state: dict) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(state, indent=2))
    os.replace(tmp_path, path)


@contextlib.contextmanager
def acquire_lock(lock_path: Path):
    """O_EXCL file lock. Unlike the Postgres advisory lock this replaces, a
    crash leaves it behind - the error message names the file so it can be
    removed by hand."""
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise LockHeldError(f"Lock already held: {lock_path}")
    os.close(fd)
    try:
        yield
    finally:
        lock_path.unlink()
