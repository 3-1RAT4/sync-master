import contextlib
import json
import os
from pathlib import Path


class LockHeldError(Exception):
    pass


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"videos": {}}
    return json.loads(path.read_text())


def save_state(path: Path, state: dict) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(state, indent=2))
    os.replace(tmp_path, path)


@contextlib.contextmanager
def acquire_lock(lock_path: Path):
    try:
        fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        raise LockHeldError(f"Lock already held: {lock_path}")
    os.close(fd)
    try:
        yield
    finally:
        lock_path.unlink()
