"""Decide an item's final status and sell time from its observations."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import UNSOLD_FINAL, Status

_LIVE = {Status.AVAILABLE, Status.RESERVED}


@dataclass(frozen=True)
class Outcome:
    final_status: str | None
    sold_after_min: timedelta | None = None
    sold_after_max: timedelta | None = None
    uncertain: bool = False


def compute_outcome(
    uploaded_at: datetime,
    observations: list[tuple[datetime, Status]],
    now: datetime,
    *,
    stop_age: timedelta,
    uncertain_gap: timedelta,
) -> Outcome:
    seen = sorted((t, s) for t, s in observations if s is not Status.UNKNOWN)
    for index, (observed_at, status) in enumerate(seen):
        if status is Status.SOLD:
            live = [t for t, s in seen[:index] if s in _LIVE]
            last_live = live[-1] if live else uploaded_at
            return Outcome(
                final_status=Status.SOLD.value,
                sold_after_min=last_live - uploaded_at,
                sold_after_max=observed_at - uploaded_at,
                uncertain=(observed_at - last_live) > uncertain_gap,
            )
        if status is Status.DELETED:
            return Outcome(final_status=Status.DELETED.value, uncertain=True)
    if now - uploaded_at >= stop_age:
        last_status = seen[-1][1] if seen else None
        return Outcome(final_status=Status.HIDDEN.value if last_status is Status.HIDDEN else UNSOLD_FINAL)
    return Outcome(final_status=None)
