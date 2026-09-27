from datetime import datetime, timedelta, timezone
from decimal import Decimal

from helpers import BASE, FakeFetcher, item_page, make_catalog_item, make_config, make_snapshot

from vinted_tracker import db
from vinted_tracker.discover import item_url
from vinted_tracker.models import FetchedPage, Status
from vinted_tracker.recheck import recheck_item

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
ROW = {"id": 1001, "uploaded_at": T0}
URL = item_url(BASE, 1001)


def track(conn):
    db.insert_item(
        conn, item=make_catalog_item(1001), snap=make_snapshot(1001), query_name="streetwear",
        uploaded_at=T0, first_seen_at=T0 + timedelta(minutes=5), next_check_at=T0 + timedelta(hours=2),
    )


def check(conn, page, hours, tmp_path, stretch=1.0):
    now = T0 + timedelta(hours=hours)
    return recheck_item(conn, FakeFetcher({URL: page}), make_config(), ROW, lambda: now, tmp_path, stretch)


def item_row(conn):
    return conn.execute("SELECT * FROM items WHERE id = 1001").fetchone()


def test_still_available_schedules_next_check(conn, tmp_path):
    track(conn)
    result = check(conn, item_page(1001), 2, tmp_path)
    assert (result.status, result.final_status, result.parse_error) == (Status.AVAILABLE, None, False)
    row = item_row(conn)
    assert row["next_check_at"] == T0 + timedelta(hours=4)
    assert row["last_checked_at"] == T0 + timedelta(hours=2)
    assert db.last_observation(conn, 1001)["raw"] is None  # unchanged status: no raw copy


def test_sold_sets_outcome_and_keeps_raw(conn, tmp_path):
    track(conn)
    result = check(conn, item_page(1001, can_buy=False, text="Vândut"), 2, tmp_path)
    assert result.final_status == "sold"
    row = item_row(conn)
    assert row["final_status"] == "sold"
    assert row["sold_after_min"] == timedelta(minutes=5)
    assert row["sold_after_max"] == timedelta(hours=2)
    assert row["next_check_at"] is None
    assert db.last_observation(conn, 1001)["raw"]["sold_text"] is True


def test_deleted_is_final(conn, tmp_path):
    track(conn)
    page = FetchedPage(url=f"{BASE}/catalog", status=200, html="<html></html>", text="")
    assert check(conn, page, 2, tmp_path).final_status == "deleted"
    assert item_row(conn)["uncertain"] is True


def test_parse_error_records_unknown_and_retries(conn, tmp_path):
    track(conn)
    page = FetchedPage(url=f"{BASE}/items/1001-x", status=200, html="<html>changed</html>", text="")
    result = check(conn, page, 2, tmp_path)
    assert result.parse_error is True
    assert db.last_observation(conn, 1001)["status"] == "unknown"
    assert item_row(conn)["next_check_at"] == T0 + timedelta(hours=4)
    assert len(list(tmp_path.glob("*item-1001.html"))) == 1


def test_price_drop_is_recorded(conn, tmp_path):
    track(conn)
    check(conn, item_page(1001, amount="60.0"), 2, tmp_path)
    assert db.last_observation(conn, 1001)["price_ron"] == Decimal("60.00")


def test_unsold_after_thirty_days(conn, tmp_path):
    track(conn)
    assert check(conn, item_page(1001), 720, tmp_path).final_status == "unsold_30d"


def test_stretch_delays_next_check(conn, tmp_path):
    track(conn)
    check(conn, item_page(1001), 2, tmp_path, stretch=2.0)
    assert item_row(conn)["next_check_at"] == T0 + timedelta(hours=6)
