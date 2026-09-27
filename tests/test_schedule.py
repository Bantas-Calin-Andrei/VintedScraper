from datetime import datetime, timedelta, timezone

from vinted_tracker.schedule import check_interval, next_check_at, stop_age, stretch_factor

SCHED = ((24.0, 2.0), (168.0, 8.0), (720.0, 24.0))
T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def test_stop_age():
    assert stop_age(SCHED) == timedelta(days=30)


def test_interval_bands():
    assert check_interval(timedelta(hours=1), SCHED) == timedelta(hours=2)
    assert check_interval(timedelta(hours=30), SCHED) == timedelta(hours=8)
    assert check_interval(timedelta(days=10), SCHED) == timedelta(hours=24)
    assert check_interval(timedelta(days=30), SCHED) is None


def test_next_check_normal():
    now = T0 + timedelta(minutes=10)
    assert next_check_at(T0, now, SCHED) == now + timedelta(hours=2)


def test_next_check_stretched():
    now = T0 + timedelta(minutes=10)
    assert next_check_at(T0, now, SCHED, stretch=1.5) == now + timedelta(hours=3)


def test_next_check_capped_at_stop():
    now = T0 + timedelta(days=29, hours=12)
    assert next_check_at(T0, now, SCHED) == T0 + timedelta(days=30)


def test_next_check_none_after_stop():
    assert next_check_at(T0, T0 + timedelta(days=30), SCHED) is None


def test_stretch_factor():
    assert stretch_factor(0, 360) == 1.0
    assert stretch_factor(288, 360) == 1.0
    assert stretch_factor(576, 360) == 2.0
