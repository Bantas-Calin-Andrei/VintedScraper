from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from helpers import BASE, FakeFetcher, item_page, make_catalog_item, make_config, make_snapshot

from vinted_tracker import db
from vinted_tracker.discover import item_url
from vinted_tracker.manual import parse_item_link, process_next_request
from vinted_tracker.models import FetchedPage

NOW = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
ITEM = 7001
URL = item_url(BASE, ITEM)


def process(conn, page, tmp_path):
    fetcher = FakeFetcher({URL: page} if page else {})
    return process_next_request(conn, fetcher, make_config(), lambda: NOW, tmp_path), fetcher


def request(conn):
    return conn.execute("SELECT * FROM manual_requests WHERE item_id = %s", (ITEM,)).fetchone()


def item(conn):
    return conn.execute("SELECT * FROM items WHERE id = %s", (ITEM,)).fetchone()


@pytest.mark.parametrize(
    ("link", "expected"),
    [
        ("https://www.vinted.ro/items/7001-geaca-nike", 7001),
        ("https://www.vinted.ro/items/7001-geaca-nike?referrer=catalog", 7001),
        ("  http://vinted.ro/items/7001  ", 7001),
        ("www.vinted.ro/items/7001-x", 7001),
        ("https://www.vinted.fr/items/7001-x", None),
        ("https://www.vinted.ro/catalog?catalog[]=2050", None),
        ("nike hoodie", None),
    ],
)
def test_parse_item_link(link, expected):
    assert parse_item_link(link) == expected


def test_no_requests_does_nothing(conn, tmp_path):
    result, fetcher = process(conn, None, tmp_path)
    assert result is None and fetcher.calls == []


def test_romanian_listing_is_added_as_manual(conn, tmp_path):
    db.add_manual_request(conn, ITEM, URL, NOW)
    result, fetcher = process(conn, item_page(ITEM, title="Geacă TNF", brand="The North Face", size="L",
                                              text="Încărcat acum 2 zile"), tmp_path)
    assert fetcher.calls == [URL]
    row = item(conn)
    assert (row["source"], row["query_name"], row["title"], row["brand"], row["size"]) == (
        "manual", "manual", "Geacă TNF", "The North Face", "L")
    assert row["condition"] == "Nou fără etichetă"
    assert row["uploaded_at"] == NOW - timedelta(days=2)
    assert row["price_listed_ron"] == Decimal("120.00") and row["price_currency"] == "RON"
    assert row["next_check_at"] == NOW + timedelta(hours=8)
    assert request(conn)["status"] == "done" and "Geacă TNF" in request(conn)["message"]
    assert result == request(conn)["message"]


def test_foreign_seller_keeps_its_own_currency(conn, tmp_path):
    db.add_manual_request(conn, ITEM, URL, NOW)
    process(conn, item_page(ITEM, currency="PLN", amount="150"), tmp_path)
    row = item(conn)
    assert row["price_listed_ron"] is None
    assert (row["price_original"], row["price_currency"]) == (Decimal("150.00"), "PLN")


def test_too_old_listing_is_refused(conn, tmp_path):
    db.add_manual_request(conn, ITEM, URL, NOW)
    process(conn, item_page(ITEM, text="Încărcat acum 2 luni"), tmp_path)
    assert item(conn) is None
    assert request(conn)["status"] == "failed"
    assert request(conn)["message"] == "Too old to track: it was posted 60 days ago."


def test_already_sold_listing_is_recorded_as_sold(conn, tmp_path):
    db.add_manual_request(conn, ITEM, URL, NOW)
    process(conn, item_page(ITEM, can_buy=False, text="Vândut\nÎncărcat acum 3 zile"), tmp_path)
    row = item(conn)
    assert row["final_status"] == "sold" and row["next_check_at"] is None
    assert row["sold_after_max"] == timedelta(days=3)
    assert request(conn)["status"] == "done"


def test_deleted_listing_fails_with_a_message(conn, tmp_path):
    db.add_manual_request(conn, ITEM, URL, NOW)
    process(conn, FetchedPage(url=f"{BASE}/catalog", status=200, html="<html></html>", text=""), tmp_path)
    assert item(conn) is None
    assert request(conn)["message"] == "This listing no longer exists on Vinted."


def test_unreadable_page_fails_and_is_saved_for_debugging(conn, tmp_path):
    db.add_manual_request(conn, ITEM, URL, NOW)
    process(conn, FetchedPage(url=f"{URL}-x", status=200, html="<html>changed</html>", text=""), tmp_path)
    assert request(conn)["status"] == "failed"
    assert len(list(tmp_path.glob(f"*manual-{ITEM}.html"))) == 1


def test_listing_already_tracked_is_not_fetched_again(conn, tmp_path):
    db.insert_item(conn, item=make_catalog_item(ITEM), snap=make_snapshot(ITEM), query_name="streetwear",
                   uploaded_at=NOW, first_seen_at=NOW, next_check_at=NOW)
    db.add_manual_request(conn, ITEM + 1, item_url(BASE, ITEM + 1), NOW)  # a real queued one
    conn.execute("INSERT INTO manual_requests (item_id, url, requested_at) VALUES (%s, %s, %s)", (ITEM, URL, NOW))
    fetcher = FakeFetcher({})
    message = process_next_request(conn, fetcher, make_config(), lambda: NOW, tmp_path)
    assert fetcher.calls == [] and message == "This listing is already being tracked."
    assert request(conn)["status"] == "done"
