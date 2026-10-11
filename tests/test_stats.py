from datetime import datetime, timedelta, timezone
from decimal import Decimal

from helpers import make_catalog_item, make_snapshot

from vinted_tracker import db, stats
from vinted_tracker.models import Status

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
BASE = "https://www.vinted.ro"


def add(conn, item_id, *, brand="Nike", catalog_id=1812, size="M", price="100", age=timedelta(days=10),
        sold=None, uncertain=False, final=None, title=None, low_price=None):
    uploaded = NOW - age
    db.insert_item(
        conn,
        item=make_catalog_item(item_id, brand=brand, size=size, price_ron=Decimal(price),
                               title=title or f"Item {item_id}"),
        snap=make_snapshot(item_id, price=Decimal(price), catalog_id=catalog_id),
        query_name="q", uploaded_at=uploaded, first_seen_at=uploaded + timedelta(minutes=5),
        next_check_at=None if (sold or final) else NOW + timedelta(hours=2),
    )
    if low_price:
        db.add_observation(conn, item_id, uploaded + timedelta(hours=1), Status.AVAILABLE, Decimal(low_price), 4, None)
    if sold:
        lo, hi = sold
        db.update_item_after_check(conn, item_id, checked_at=uploaded + timedelta(hours=hi), next_check_at=None,
                                   final_status="sold", sold_after_min=timedelta(hours=lo),
                                   sold_after_max=timedelta(hours=hi), uncertain=uncertain)
    elif final:
        db.update_item_after_check(conn, item_id, checked_at=NOW, next_check_at=None, final_status=final,
                                   sold_after_min=None, sold_after_max=None, uncertain=final == "deleted")


def test_tiles(conn):
    add(conn, 1, sold=(1, 3))
    add(conn, 2, sold=(3, 5))
    add(conn, 3, sold=(5, 7))
    add(conn, 4, final="deleted")
    add(conn, 5, age=timedelta(hours=3))
    add(conn, 6, sold=(200, 220), uncertain=True)
    t = stats.tiles(conn, NOW)
    assert (t["tracking"], t["sold"], t["deleted"]) == (1, 4, 1)
    assert t["median_hours"] == 4.0  # uncertain sale left out
    assert t["pct_sold_7d"] == 60.0  # 3 of the 5 items older than 7 days sold within 7 days


def test_tiles_on_empty_database(conn):
    assert stats.tiles(conn, NOW) == {"tracking": 0, "sold": 0, "deleted": 0, "median_hours": None, "pct_sold_7d": None}


def test_chart_series_needs_three_sales_per_bar(conn):
    for i, (lo, hi) in enumerate([(1, 3), (3, 5), (5, 7)], start=1):
        add(conn, i, brand="Nike", sold=(lo, hi))
    add(conn, 4, brand="Lacoste", sold=(1, 3))
    series = stats.chart_series(conn)
    assert series["brand"] == [{"label": "Nike", "median_hours": 4.0, "count": 3}]
    assert series["type"] == [{"label": "Pulovere", "median_hours": 3.0, "count": 4}]
    assert series["price_band"] == [{"label": "100-199 RON", "median_hours": 3.0, "count": 4}]


def test_products_rows_and_formatting(conn):
    add(conn, 1, sold=(4, 6), title="Hanorac Nike", age=timedelta(days=2))
    add(conn, 2, age=timedelta(minutes=40), low_price="99", price="120", brand="Lacoste", catalog_id=1803)
    rows, total = stats.products(conn, NOW, base_url=BASE)
    assert total == 2
    newest, sold = rows
    assert newest["status"] == "tracking" and newest["status_label"] == "Tracking"
    assert newest["price_text"] == "120 → 99 RON"
    assert newest["type"] == "Topuri și tricouri"
    assert newest["listed_ago"] == "40 min ago"
    assert newest["next_check_in"] == "in 2 h"
    assert newest["favourites"] == 4
    assert sold["sold_after_text"] == "4–6 h"
    assert sold["link"] == f"{BASE}/items/1-hanorac-nike"


def test_products_filters_and_paging(conn):
    add(conn, 1, sold=(4, 6), brand="Nike")
    add(conn, 2, brand="Lacoste", catalog_id=257, title="Blugi Lacoste")
    add(conn, 3, final="deleted", brand="Nike")
    db.mark_out_of_scope(conn, [3])
    assert [r["id"] for r in stats.products(conn, NOW, status="sold", base_url=BASE)[0]] == [1]
    assert [r["id"] for r in stats.products(conn, NOW, brand="Lacoste", base_url=BASE)[0]] == [2]
    assert [r["id"] for r in stats.products(conn, NOW, type_id=257, base_url=BASE)[0]] == [2]
    assert [r["id"] for r in stats.products(conn, NOW, q="blugi", base_url=BASE)[0]] == [2]
    assert stats.products(conn, NOW, page=2, base_url=BASE) == ([], 0)
    assert stats.distinct_brands(conn) == ["Lacoste", "Nike"]


def test_sold_after_text_for_long_and_uncertain_sales(conn):
    add(conn, 1, sold=(50, 70), uncertain=True)
    (row,), _ = stats.products(conn, NOW, base_url=BASE)
    assert row["sold_after_text"] == "≈ 2.1–2.9 d"


def test_tracker_state_never_reported():
    assert stats.tracker_state(None, NOW)["level"] == "stopped"


def test_tracker_state_running():
    state = stats.tracker_state(({"health": "ok", "this_run": {"blocks": 2}}, NOW - timedelta(minutes=1)), NOW)
    assert state == {"level": "ok", "text": "Running · last check 1 min ago", "blocks": 2}


def test_tracker_state_stopped_when_heartbeat_is_old():
    state = stats.tracker_state(({"health": "ok"}, NOW - timedelta(minutes=14)), NOW)
    assert state["level"] == "stopped" and "14 min" in state["text"]


def test_tracker_state_blocked_pause_is_not_stopped():
    data = {"health": "blocked", "paused_until": (NOW + timedelta(hours=2)).isoformat(), "last_error": "challenge"}
    state = stats.tracker_state((data, NOW - timedelta(hours=2)), NOW)
    assert state["level"] == "warn"
    assert state["text"] == "Blocked by Vinted · pausing until 17:00"


def test_tracker_state_parser_broken():
    state = stats.tracker_state(({"health": "parser_broken"}, NOW), NOW)
    assert state["level"] == "warn" and "debug" in state["text"]
