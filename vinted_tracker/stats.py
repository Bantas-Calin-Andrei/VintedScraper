"""Numbers, chart series, product rows and tracker state for the dashboard."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from statistics import median
from zoneinfo import ZoneInfo

import psycopg

from .vinted_ref import PRODUCT_TYPES, catalog_ids_of_type, product_type_of

MIN_SOLD_PER_BAR = 3
PAGE_SIZE = 50
LOCAL_TZ = ZoneInfo("Europe/Bucharest")
STATUS_LABELS = {"tracking": "Tracking", "sold": "Sold", "deleted": "Deleted", "unsold_30d": "Unsold 30 d", "hidden": "Hidden"}

_HOURS = "(extract(epoch FROM (sold_after_min + sold_after_max) / 2) / 3600)::float8"


def tiles(conn: psycopg.Connection, now: datetime) -> dict:
    row = conn.execute(
        f"""
        SELECT count(*) FILTER (WHERE final_status IS NULL) AS tracking,
               count(*) FILTER (WHERE final_status = 'sold') AS sold,
               count(*) FILTER (WHERE final_status = 'deleted') AS deleted,
               percentile_cont(0.5) WITHIN GROUP (ORDER BY {_HOURS})
                   FILTER (WHERE final_status = 'sold' AND NOT uncertain) AS median_hours,
               count(*) FILTER (WHERE final_status = 'sold' AND sold_after_max <= interval '7 days'
                                AND %(now)s - uploaded_at >= interval '7 days') AS sold_7d,
               count(*) FILTER (WHERE %(now)s - uploaded_at >= interval '7 days') AS old_7d
        FROM items WHERE NOT out_of_scope
        """,
        {"now": now},
    ).fetchone()
    return {
        "tracking": row["tracking"],
        "sold": row["sold"],
        "deleted": row["deleted"],
        "median_hours": None if row["median_hours"] is None else round(row["median_hours"], 1),
        "pct_sold_7d": round(100.0 * row["sold_7d"] / row["old_7d"], 1) if row["old_7d"] else None,
    }


def price_band(price: Decimal | None) -> str:
    if price is None:
        return "(none)"
    for limit, label in ((50, "0-49 RON"), (100, "50-99 RON"), (200, "100-199 RON"), (400, "200-399 RON")):
        if price < limit:
            return label
    return "400+ RON"


def chart_series(conn: psycopg.Connection) -> dict[str, list[dict]]:
    rows = conn.execute(
        f"""
        SELECT brand, catalog_id, size, price_listed_ron, {_HOURS} AS hours FROM items
        WHERE NOT out_of_scope AND final_status = 'sold' AND NOT uncertain
        """
    ).fetchall()
    keys = {
        "brand": lambda r: r["brand"] or "(none)",
        "type": lambda r: product_type_of(r["catalog_id"]) or "(other)",
        "size": lambda r: r["size"] or "(none)",
        "price_band": lambda r: price_band(r["price_listed_ron"]),
    }
    series: dict[str, list[dict]] = {}
    for dim, key in keys.items():
        buckets: dict[str, list[float]] = defaultdict(list)
        for r in rows:
            buckets[key(r)].append(float(r["hours"]))
        series[dim] = sorted(
            (
                {"label": label, "median_hours": round(median(hours), 1), "count": len(hours)}
                for label, hours in buckets.items()
                if len(hours) >= MIN_SOLD_PER_BAR
            ),
            key=lambda b: (b["median_hours"], b["label"]),
        )
    return series


def distinct_brands(conn: psycopg.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT brand FROM items WHERE NOT out_of_scope AND brand IS NOT NULL ORDER BY brand"
    ).fetchall()
    return [r["brand"] for r in rows]


def products(
    conn: psycopg.Connection,
    now: datetime,
    *,
    status: str = "",
    brand: str = "",
    type_id: int | None = None,
    q: str = "",
    page: int = 1,
    base_url: str = "https://www.vinted.ro",
) -> tuple[list[dict], int]:
    where = ["NOT i.out_of_scope"]
    params: dict = {"limit": PAGE_SIZE, "offset": (max(page, 1) - 1) * PAGE_SIZE}
    if status == "tracking":
        where.append("i.final_status IS NULL")
    elif status in STATUS_LABELS:
        where.append("i.final_status = %(status)s")
        params["status"] = status
    if brand:
        where.append("i.brand = %(brand)s")
        params["brand"] = brand
    if type_id in PRODUCT_TYPES:
        where.append("i.catalog_id = ANY(%(cats)s)")
        params["cats"] = list(catalog_ids_of_type(type_id))
    if q.strip():
        where.append("(i.title ILIKE %(q)s OR i.brand ILIKE %(q)s)")
        params["q"] = f"%{q.strip()}%"
    rows = conn.execute(
        f"""
        SELECT i.id, i.title, i.url, i.brand, i.catalog_id, i.size, i.condition, i.price_listed_ron,
               i.uploaded_at, i.final_status, i.sold_after_min, i.sold_after_max, i.uncertain,
               i.last_checked_at, i.next_check_at, lp.lowest_price, lp.favourites, count(*) OVER () AS total
        FROM items i
        LEFT JOIN LATERAL (
            SELECT min(o.price_ron) AS lowest_price,
                   (array_agg(o.favourite_count ORDER BY o.observed_at DESC)
                        FILTER (WHERE o.favourite_count IS NOT NULL))[1] AS favourites
            FROM observations o WHERE o.item_id = i.id
        ) lp ON true
        WHERE {' AND '.join(where)}
        ORDER BY i.uploaded_at DESC, i.id DESC
        LIMIT %(limit)s OFFSET %(offset)s
        """,
        params,
    ).fetchall()
    total = rows[0]["total"] if rows else 0
    return [_format(r, now, base_url) for r in rows], total


def _format(r: dict, now: datetime, base_url: str) -> dict:
    status = r["final_status"] or "tracking"
    return {
        "id": r["id"],
        "title": r["title"],
        "link": base_url + r["url"],
        "brand": r["brand"] or "",
        "type": product_type_of(r["catalog_id"]) or "",
        "size": r["size"] or "",
        "condition": r["condition"] or "",
        "status": status,
        "status_label": STATUS_LABELS.get(status, status),
        "price_text": _price_text(r["price_listed_ron"], r["lowest_price"]),
        "listed_ago": _ago(now - r["uploaded_at"]),
        "sold_after_text": _sold_after(r) if status == "sold" else "",
        "favourites": r["favourites"],
        "last_checked_ago": _ago(now - r["last_checked_at"]) if r["last_checked_at"] else "",
        "next_check_in": _in(r["next_check_at"] - now) if r["next_check_at"] and status == "tracking" else "",
    }


def _money(value: Decimal) -> str:
    return f"{value:.0f}" if value == value.to_integral_value() else f"{value:.2f}"


def _price_text(listed: Decimal | None, lowest: Decimal | None) -> str:
    if listed is None:
        return ""
    if lowest is not None and lowest < listed:
        return f"{_money(listed)} → {_money(lowest)} RON"
    return f"{_money(listed)} RON"


def _sold_after(r: dict) -> str:
    lo = r["sold_after_min"].total_seconds() / 3600
    hi = r["sold_after_max"].total_seconds() / 3600
    text = f"{lo:.0f}–{hi:.0f} h" if hi < 48 else f"{lo / 24:.1f}–{hi / 24:.1f} d"
    return ("≈ " if r["uncertain"] else "") + text


def _span(delta: timedelta) -> str:
    minutes = int(delta.total_seconds() // 60)
    if minutes < 60:
        return f"{minutes} min"
    if minutes < 48 * 60:
        return f"{minutes // 60} h"
    return f"{minutes // 1440} d"


def _ago(delta: timedelta) -> str:
    return "just now" if delta < timedelta(minutes=1) else f"{_span(delta)} ago"


def _in(delta: timedelta) -> str:
    return "now" if delta < timedelta(minutes=1) else f"in {_span(delta)}"


def tracker_state(row: tuple[dict, datetime] | None, now: datetime, stale_after: timedelta = timedelta(minutes=10)) -> dict:
    if row is None:
        return {"level": "stopped", "text": "Tracker hasn't reported yet", "blocks": None}
    data, updated = row
    blocks = (data.get("this_run") or {}).get("blocks")
    paused_until = datetime.fromisoformat(data["paused_until"]) if data.get("paused_until") else None
    if data.get("health") == "blocked" and paused_until and paused_until > now:
        until = paused_until.astimezone(LOCAL_TZ).strftime("%H:%M")
        return {"level": "warn", "text": f"Blocked by Vinted · pausing until {until}", "blocks": blocks}
    age = now - updated
    if age >= stale_after:
        return {"level": "stopped", "text": f"Tracker stopped (no check for {_span(age)})", "blocks": blocks}
    health = data.get("health", "ok")
    if health == "parser_broken":
        return {"level": "warn", "text": "Vinted pages changed: parsing fails, see debug/", "blocks": blocks}
    if health == "network_error":
        return {"level": "warn", "text": f"Pages not loading · {data.get('last_error') or ''}".strip(" ·"), "blocks": blocks}
    if health == "blocked":
        return {"level": "warn", "text": "Blocked by Vinted", "blocks": blocks}
    return {"level": "ok", "text": f"Running · last check {_ago(age)}", "blocks": blocks}
