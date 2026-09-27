"""When to check a tracked item next."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

Schedule = Sequence[tuple[float, float]]  # (max_age_hours, interval_hours), ascending


def stop_age(schedule: Schedule) -> timedelta:
    """Age at which tracking stops: the last row's max age."""
    return timedelta(hours=schedule[-1][0])


def check_interval(age: timedelta, schedule: Schedule) -> timedelta | None:
    hours = age.total_seconds() / 3600
    for max_age_hours, interval_hours in schedule:
        if hours < max_age_hours:
            return timedelta(hours=interval_hours)
    return None


def next_check_at(uploaded_at: datetime, now: datetime, schedule: Schedule, stretch: float = 1.0) -> datetime | None:
    """Next check time, never later than the stop age; None once the item has reached it."""
    interval = check_interval(now - uploaded_at, schedule)
    if interval is None:
        return None
    return min(now + interval * stretch, uploaded_at + stop_age(schedule))


def stretch_factor(due_count: int, max_pages_per_hour: int, recheck_share: float = 0.8) -> float:
    """>1 when more rechecks are due than one hour of page budget can handle (the rate never increases)."""
    capacity = max_pages_per_hour * recheck_share
    if capacity <= 0:
        return 1.0
    return max(1.0, due_count / capacity)
