"""Re-check one tracked item and update its observations and outcome."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import psycopg

from . import db
from .browser import Fetcher, FetchError, save_debug_page
from .config import Config
from .discover import item_url
from .models import ItemSnapshot, Status
from .outcome import Outcome, compute_outcome
from .parse import ParseError, parse_item
from .schedule import next_check_at, stop_age

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecheckResult:
    status: Status
    parse_error: bool
    final_status: str | None


def recheck_item(
    conn: psycopg.Connection,
    fetcher: Fetcher,
    cfg: Config,
    row: dict,
    clock: Callable[[], datetime],
    debug_dir: Path,
    stretch: float = 1.0,
) -> RecheckResult:
    item_id, uploaded_at = row["id"], row["uploaded_at"]
    try:
        page = fetcher.fetch(item_url(cfg.base_url, item_id))
    except FetchError:
        # Skip until the next cycle so one unreachable page can't block every other recheck.
        _record(conn, cfg, item_id, uploaded_at, clock(), None, stretch)
        raise
    now = clock()
    snap: ItemSnapshot | None
    try:
        snap = parse_item(page, item_id)
    except ParseError as exc:
        log.warning("item %s: %s", item_id, exc)
        save_debug_page(page, f"item-{item_id}", debug_dir)
        snap = None
    outcome = _record(conn, cfg, item_id, uploaded_at, now, snap, stretch)
    if outcome.final_status:
        log.info("item %s finished: %s", item_id, outcome.final_status)
    status = snap.status if snap is not None else Status.UNKNOWN
    return RecheckResult(status=status, parse_error=snap is None, final_status=outcome.final_status)


def _record(
    conn: psycopg.Connection,
    cfg: Config,
    item_id: int,
    uploaded_at: datetime,
    now: datetime,
    snap: ItemSnapshot | None,
    stretch: float,
) -> Outcome:
    """Store one observation and the item's resulting outcome and next check."""
    status = snap.status if snap is not None else Status.UNKNOWN
    previous = db.last_observation(conn, item_id)
    changed = snap is not None and (previous is None or previous["status"] != status.value)
    db.add_observation(
        conn,
        item_id,
        now,
        status,
        snap.price if snap is not None and snap.currency == "RON" else None,
        snap.favourite_count if snap is not None else None,
        snap.raw if changed else None,
    )

    schedule = cfg.recheck_schedule
    uncertain_gap = timedelta(hours=cfg.uncertain_gap_hours)
    outcome = compute_outcome(
        uploaded_at,
        db.observations_for(conn, item_id),
        now,
        stop_age=stop_age(schedule),
        uncertain_gap=uncertain_gap,
    )
    nxt = None
    if not outcome.final_status:
        nxt = next_check_at(uploaded_at, now, schedule, stretch, max_interval=uncertain_gap / 2)
    db.update_item_after_check(
        conn,
        item_id,
        checked_at=now,
        next_check_at=nxt,
        final_status=outcome.final_status,
        sold_after_min=outcome.sold_after_min,
        sold_after_max=outcome.sold_after_max,
        uncertain=outcome.uncertain,
    )
    return outcome
