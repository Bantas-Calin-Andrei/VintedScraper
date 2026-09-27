"""Find brand-new listings for a watchlist query and start tracking the ones that qualify."""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

import psycopg

from . import db
from .browser import Fetcher, save_debug_page
from .config import Config, Query
from .models import CatalogItem, ItemSnapshot, Status
from .parse import ParseError, parse_catalog, parse_item
from .schedule import next_check_at

log = logging.getLogger(__name__)


@dataclass
class DiscoverResult:
    baseline: bool = False
    candidates: int = 0
    tracked: int = 0
    skipped: int = 0
    parse_errors: int = 0


def build_catalog_url(base_url: str, q: Query, page: int = 1) -> str:
    params: list[tuple[str, object]] = [("catalog[]", c) for c in q.catalog_ids]
    params += [("brand_ids[]", b) for b in q.brand_ids]
    if q.price_from is not None:
        params.append(("price_from", _number(q.price_from)))
    if q.price_to is not None:
        params.append(("price_to", _number(q.price_to)))
    params.append(("order", "newest_first"))
    if page > 1:
        params.append(("page", page))
    return f"{base_url}/catalog?{urlencode(params, safe='[]')}"


def item_url(base_url: str, item_id: int) -> str:
    return f"{base_url}/items/{item_id}"


def reject_reason(snap: ItemSnapshot, max_age: timedelta) -> str | None:
    if snap.status is not Status.AVAILABLE:
        return f"status_{snap.status.value}"
    if snap.currency != "RON":
        return "foreign_seller"
    if snap.upload_age is None:
        return "no_upload_age"
    if snap.upload_age >= max_age:
        return "too_old"
    return None


def discover_query(
    conn: psycopg.Connection,
    fetcher: Fetcher,
    cfg: Config,
    q: Query,
    clock: Callable[[], datetime],
    debug_dir: Path,
) -> DiscoverResult:
    result = DiscoverResult()
    state = db.get_query_state(conn, q.name)
    items = _load_catalog(fetcher, cfg, q, 1, debug_dir, result)
    if items is None:
        return result
    if state is None:
        high_water = max((i.id for i in items), default=0)
        db.set_query_state(conn, q.name, high_water, clock())
        result.baseline = True
        log.info("query %s: baseline set at item %s; tracking starts next poll", q.name, high_water)
        return result

    high_water = state[0]
    if items and min(i.id for i in items) > high_water:
        items = items + (_load_catalog(fetcher, cfg, q, 2, debug_dir, result) or [])
    fresh = sorted({i.id: i for i in items if i.id > high_water}.values(), key=lambda i: i.id)
    for item in fresh:
        if db.is_known(conn, item.id):
            continue
        result.candidates += 1
        reason = _catalog_reject_reason(conn, cfg, q, item, clock())
        if reason is None:
            reason = _try_track(conn, fetcher, cfg, q, item, clock, debug_dir, result)
        if reason is not None:
            db.add_skipped(conn, item.id, reason, clock())
            result.skipped += 1
    db.set_query_state(conn, q.name, max([high_water] + [i.id for i in items]), clock())
    log.info(
        "query %s: %s candidates, %s tracked, %s skipped",
        q.name, result.candidates, result.tracked, result.skipped,
    )
    return result


def _load_catalog(
    fetcher: Fetcher, cfg: Config, q: Query, page_no: int, debug_dir: Path, result: DiscoverResult
) -> list[CatalogItem] | None:
    page = fetcher.fetch(build_catalog_url(cfg.base_url, q, page_no))
    try:
        return parse_catalog(page.html)
    except ParseError as exc:
        log.warning("query %s page %s: %s", q.name, page_no, exc)
        save_debug_page(page, f"catalog-{q.name}-p{page_no}", debug_dir)
        result.parse_errors += 1
        return None


def hourly_quota(cfg: Config) -> int:
    """Per-query share of the daily cap for one hour, so the sample spreads over the day and across queries."""
    return math.ceil(cfg.max_new_per_day / 24 / len(cfg.queries))


def _catalog_reject_reason(
    conn: psycopg.Connection, cfg: Config, q: Query, item: CatalogItem, now: datetime
) -> str | None:
    if db.count_new_since(conn, now - timedelta(days=1)) >= cfg.max_new_per_day:
        return "daily_cap"
    if db.count_new_since(conn, now - timedelta(hours=1), q.name) >= hourly_quota(cfg):
        return "hourly_cap"
    price = item.price_ron
    if cfg.whole_price_prefilter and price is not None and price != price.to_integral_value():
        return "likely_foreign"
    return None


def _try_track(
    conn: psycopg.Connection,
    fetcher: Fetcher,
    cfg: Config,
    q: Query,
    item: CatalogItem,
    clock: Callable[[], datetime],
    debug_dir: Path,
    result: DiscoverResult,
) -> str | None:
    """Return a skip reason, or None if the item is now tracked."""
    page = fetcher.fetch(item_url(cfg.base_url, item.id))
    try:
        snap = parse_item(page, item.id)
    except ParseError as exc:
        log.warning("item %s: %s", item.id, exc)
        save_debug_page(page, f"item-{item.id}", debug_dir)
        result.parse_errors += 1
        return "parse_error"
    reason = reject_reason(snap, timedelta(minutes=cfg.max_item_age_minutes))
    if reason is not None:
        return reason
    now = clock()
    uploaded_at = now - snap.upload_age
    db.insert_item(
        conn,
        item=item,
        snap=snap,
        query_name=q.name,
        uploaded_at=uploaded_at,
        first_seen_at=now,
        next_check_at=next_check_at(uploaded_at, now, cfg.recheck_schedule),
    )
    result.tracked += 1
    return None


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)
