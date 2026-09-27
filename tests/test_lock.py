import pytest

from vinted_tracker.lock import AlreadyRunning, single_instance


def test_second_instance_is_refused(tmp_path):
    lock_path = tmp_path / "tracker.lock"
    with single_instance(lock_path):
        with pytest.raises(AlreadyRunning):
            with single_instance(lock_path):
                pass


def test_lock_is_released_on_exit(tmp_path):
    lock_path = tmp_path / "tracker.lock"
    with single_instance(lock_path):
        pass
    with single_instance(lock_path):
        pass
