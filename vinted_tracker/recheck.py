"""Re-check one tracked item and update its observations and outcome."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import psycopg

from . import db
from .browser import Fetcher, save_debug_page
from .config import Config
from .discover import item_url
from .models import ItemSnapshot, Status
from .outcome import compute_outcome
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
    page = fetcher.fetch(item_url(cfg.base_url, item_id))
    now = clock()
    snap: ItemSnapshot | None
    try:
        snap = parse_item(page, item_id)
    except ParseError as exc:
        log.warning("item %s: %s", item_id, exc)
        save_debug_page(page, f"item-{item_id}", debug_dir)
        snap = None

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
    outcome = compute_outcome(
        uploaded_at,
        db.observations_for(conn, item_id),
        now,
        stop_age=stop_age(schedule),
        uncertain_gap=timedelta(hours=cfg.uncertain_gap_hours),
    )
    db.update_item_after_check(
        conn,
        item_id,
        checked_at=now,
        next_check_at=None if outcome.final_status else next_check_at(uploaded_at, now, schedule, stretch),
        final_status=outcome.final_status,
        sold_after_min=outcome.sold_after_min,
        sold_after_max=outcome.sold_after_max,
        uncertain=outcome.uncertain,
    )
    if outcome.final_status:
        log.info("item %s finished: %s", item_id, outcome.final_status)
    return RecheckResult(status=status, parse_error=snap is None, final_status=outcome.final_status)
