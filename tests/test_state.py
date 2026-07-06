import pytest

from sync_master.state import LockHeldError, acquire_lock, load_state, save_state


def test_load_state_returns_empty_structure_when_file_missing(tmp_path):
    state = load_state(tmp_path / "state.json")

    assert state == {"videos": {}}


def test_save_then_load_round_trips_data(tmp_path):
    path = tmp_path / "state.json"
    original = {"videos": {"abc123": {"title": "Test Video"}}}

    save_state(path, original)
    loaded = load_state(path)

    assert loaded == original


def test_save_state_leaves_no_temp_file_behind(tmp_path):
    path = tmp_path / "state.json"

    save_state(path, {"videos": {}})

    leftover = list(tmp_path.glob("*.tmp"))
    assert leftover == []


def test_acquire_lock_blocks_concurrent_acquisition(tmp_path):
    lock_path = tmp_path / "state.json.lock"

    with acquire_lock(lock_path):
        with pytest.raises(LockHeldError):
            with acquire_lock(lock_path):
                pass


def test_acquire_lock_can_be_reacquired_after_release(tmp_path):
    lock_path = tmp_path / "state.json.lock"

    with acquire_lock(lock_path):
        pass

    with acquire_lock(lock_path):
        pass
