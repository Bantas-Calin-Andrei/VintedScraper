"""Listings added by hand from the dashboard: validate the link, then let the tracker fetch and start tracking them."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import psycopg

from . import db
from .browser import Fetcher, save_debug_page
from .config import Config
from .discover import item_url
from .models import CatalogItem, Status
from .outcome import compute_outcome
from .parse import ParseError, parse_item, parse_item_details
from .schedule import next_check_at, stop_age

log = logging.getLogger(__name__)
_LINK_RE = re.compile(r"^(?:https?://)?(?:www\.)?vinted\.ro/items/(\d+)(?:[-/?#].*)?$", re.IGNORECASE)


def parse_item_link(text: str) -> int | None:
    """The listing id from a vinted.ro listing link, or None if it isn't one."""
    match = _LINK_RE.match(text.strip())
    return int(match.group(1)) if match else None


def process_next_request(
    conn: psycopg.Connection,
    fetcher: Fetcher,
    cfg: Config,
    clock: Callable[[], datetime],
    debug_dir: Path,
) -> str | None:
    """Handle the oldest queued link. Returns the message shown in the dashboard, or None if the queue is empty.

    Page-load errors (blocked, network) propagate, leaving the request queued for the next attempt.
    """
    request = db.next_manual_request(conn)
    if request is None:
        return None
    item_id = request["item_id"]
    if conn.execute("SELECT 1 FROM items WHERE id = %s", (item_id,)).fetchone():
        return _finish(conn, item_id, "done", "This listing is already being tracked.", clock())

    page = fetcher.fetch(item_url(cfg.base_url, item_id))
    now = clock()
    try:
        snap = parse_item(page, item_id)
        details = parse_item_details(page)
    except ParseError as exc:
        log.warning("manual item %s: %s", item_id, exc)
        save_debug_page(page, f"manual-{item_id}", debug_dir)
        return _finish(conn, item_id, "failed", "Couldn't read this listing's page. Try again later.", now)
    if snap.status is Status.DELETED:
        return _finish(conn, item_id, "failed", "This listing no longer exists on Vinted.", now)

    age = snap.upload_age or timedelta(0)
    if age >= stop_age(cfg.recheck_schedule):
        return _finish(conn, item_id, "failed", f"Too old to track: it was posted {age.days} days ago.", now)

    uploaded_at = now - age
    title = details["title"] or f"Listing {item_id}"
    item = CatalogItem(
        id=item_id,
        title=title,
        url=urlparse(page.url).path,
        price_ron=snap.price if snap.currency == "RON" else None,
        favourite_count=snap.favourite_count,
        seller_id=None,
        brand=details["brand"],
        size=details["size"],
        condition=details["condition"],
        raw={"manual": True, "link": request["url"]},
    )
    db.insert_item(
        conn, item=item, snap=snap, query_name="manual", uploaded_at=uploaded_at, first_seen_at=now,
        next_check_at=next_check_at(uploaded_at, now, cfg.recheck_schedule), source="manual",
    )
    if snap.status is not Status.AVAILABLE:
        outcome = compute_outcome(
            uploaded_at, db.observations_for(conn, item_id), now,
            stop_age=stop_age(cfg.recheck_schedule), uncertain_gap=timedelta(hours=cfg.uncertain_gap_hours),
        )
        if outcome.final_status:
            db.update_item_after_check(
                conn, item_id, checked_at=now, next_check_at=None, final_status=outcome.final_status,
                sold_after_min=outcome.sold_after_min, sold_after_max=outcome.sold_after_max, uncertain=outcome.uncertain,
            )
    log.info("manual item %s added: %s", item_id, title)
    return _finish(conn, item_id, "done", f"Added: {title}", now)


def _finish(conn: psycopg.Connection, item_id: int, status: str, message: str, now: datetime) -> str:
    db.finish_manual_request(conn, item_id, status, message, now)
    return message
