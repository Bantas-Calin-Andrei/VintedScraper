from datetime import datetime, timedelta, timezone

from helpers import BASE, FakeFetcher, catalog_entry, catalog_html, catalog_page, item_page, make_config

from vinted_tracker import db
from vinted_tracker.config import Query
from vinted_tracker.discover import build_catalog_url, discover_query, item_url
from vinted_tracker.models import FetchedPage

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
Q = Query("streetwear", (5,), (53,))
CAT1 = build_catalog_url(BASE, Q)
CAT2 = build_catalog_url(BASE, Q, page=2)


def run(conn, fetcher, cfg=None, tmp_path=None):
    return discover_query(conn, fetcher, cfg or make_config(), Q, lambda: NOW, tmp_path)


def test_build_catalog_url():
    q = Query("x", (5,), (53, 14), 50.0, None)
    assert build_catalog_url(BASE, q) == (
        "https://www.vinted.ro/catalog?catalog[]=5&brand_ids[]=53&brand_ids[]=14&price_from=50&order=newest_first"
    )
    assert build_catalog_url(BASE, q, page=2).endswith("&order=newest_first&page=2")
    assert item_url(BASE, 7) == "https://www.vinted.ro/items/7"


def test_first_poll_only_sets_baseline(conn, tmp_path):
    fetcher = FakeFetcher({CAT1: catalog_page(CAT1, [300, 299, 298])})
    result = run(conn, fetcher, tmp_path=tmp_path)
    assert result.baseline is True
    assert db.get_query_state(conn, "streetwear") == (300, NOW)
    assert fetcher.calls == [CAT1]


def test_tracks_fresh_romanian_items_and_skips_the_rest(conn, tmp_path):
    db.set_query_state(conn, "streetwear", 298, NOW - timedelta(minutes=5))
    fetcher = FakeFetcher({
        CAT1: catalog_page(CAT1, [301, 300, 299, 298]),
        item_url(BASE, 299): item_page(299),
        item_url(BASE, 300): item_page(300, currency="PLN", amount="150"),
        item_url(BASE, 301): item_page(301, text="Încărcat acum 2 ore"),
    })
    result = run(conn, fetcher, tmp_path=tmp_path)
    assert (result.candidates, result.tracked, result.skipped) == (3, 1, 2)
    row = conn.execute("SELECT * FROM items WHERE id = 299").fetchone()
    assert row["uploaded_at"] == NOW - timedelta(minutes=3)
    assert row["next_check_at"] == NOW + timedelta(hours=2)
    assert row["query_name"] == "streetwear"
    reasons = {r["id"]: r["reason"] for r in conn.execute("SELECT id, reason FROM skipped_items").fetchall()}
    assert reasons == {300: "foreign_seller", 301: "too_old"}
    assert db.get_query_state(conn, "streetwear") == (301, NOW)


def test_fetches_page_two_when_all_of_page_one_is_new(conn, tmp_path):
    db.set_query_state(conn, "streetwear", 100, NOW - timedelta(minutes=5))
    pages = {CAT1: catalog_page(CAT1, [205, 204]), CAT2: catalog_page(CAT2, [203, 150, 99])}
    pages.update({item_url(BASE, i): item_page(i) for i in (150, 203, 204, 205)})
    result = run(conn, FakeFetcher(pages), tmp_path=tmp_path)
    assert result.tracked == 4


def test_known_items_are_not_refetched(conn, tmp_path):
    db.set_query_state(conn, "streetwear", 298, NOW - timedelta(minutes=5))
    db.add_skipped(conn, 300, "foreign_seller", NOW)
    fetcher = FakeFetcher({CAT1: catalog_page(CAT1, [300, 298])})  # 298 = high-water mark, so no page 2
    result = run(conn, fetcher, tmp_path=tmp_path)
    assert fetcher.calls == [CAT1]
    assert result.candidates == 0


def test_daily_cap_skips_without_fetching(conn, tmp_path):
    db.set_query_state(conn, "streetwear", 10, NOW - timedelta(minutes=5))
    fetcher = FakeFetcher({CAT1: catalog_page(CAT1, [12, 11, 10]), item_url(BASE, 11): item_page(11)})
    result = run(conn, fetcher, cfg=make_config(max_new_per_day=1), tmp_path=tmp_path)
    assert result.tracked == 1
    assert item_url(BASE, 12) not in fetcher.calls
    assert conn.execute("SELECT reason FROM skipped_items WHERE id = 12").fetchone()["reason"] == "daily_cap"


def test_decimal_price_prefilter_skips_without_fetching(conn, tmp_path):
    db.set_query_state(conn, "streetwear", 10, NOW - timedelta(minutes=5))
    page = FetchedPage(
        url=CAT1, status=200, html=catalog_html(catalog_entry(11, price="91.51"), catalog_entry(10)), text=""
    )
    fetcher = FakeFetcher({CAT1: page})
    result = run(conn, fetcher, tmp_path=tmp_path)
    assert fetcher.calls == [CAT1]
    assert result.skipped == 1
    assert conn.execute("SELECT reason FROM skipped_items WHERE id = 11").fetchone()["reason"] == "likely_foreign"


def test_catalog_parse_error_saves_debug_page(conn, tmp_path):
    fetcher = FakeFetcher({CAT1: FetchedPage(url=CAT1, status=200, html="<html>changed</html>", text="")})
    result = run(conn, fetcher, tmp_path=tmp_path)
    assert result.parse_errors == 1
    assert db.get_query_state(conn, "streetwear") is None
    assert len(list(tmp_path.glob("*catalog-streetwear-p1.html"))) == 1


def test_hourly_quota_per_query_spreads_the_daily_cap(conn, tmp_path):
    db.set_query_state(conn, "streetwear", 10, NOW - timedelta(minutes=5))
    fetcher = FakeFetcher({CAT1: catalog_page(CAT1, [12, 11, 10]), item_url(BASE, 11): item_page(11)})
    result = run(conn, fetcher, cfg=make_config(max_new_per_day=24), tmp_path=tmp_path)  # 1 per hour
    assert result.tracked == 1
    assert item_url(BASE, 12) not in fetcher.calls
    assert conn.execute("SELECT reason FROM skipped_items WHERE id = 12").fetchone()["reason"] == "hourly_cap"
