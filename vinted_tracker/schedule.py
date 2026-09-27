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


def next_check_at(
    uploaded_at: datetime,
    now: datetime,
    schedule: Schedule,
    stretch: float = 1.0,
    max_interval: timedelta | None = None,
) -> datetime | None:
    """Next check time, never later than the stop age; None once the item has reached it.

    `max_interval` bounds a stretched interval so a backlog never pushes checks far enough
    apart to make sales `uncertain` (it never shortens the configured interval).
    """
    interval = check_interval(now - uploaded_at, schedule)
    if interval is None:
        return None
    stretched = interval * stretch
    if max_interval is not None:
        stretched = max(interval, min(stretched, max_interval))
    return min(now + stretched, uploaded_at + stop_age(schedule))


def stretch_factor(
    due_count: int, max_pages_per_hour: int, recheck_share: float = 0.8, max_stretch: float = 2.0
) -> float:
    """>1 when more rechecks are due than one hour of page budget can handle (the rate never increases)."""
    capacity = max_pages_per_hour * recheck_share
    if capacity <= 0:
        return 1.0
    return min(max_stretch, max(1.0, due_count / capacity))
