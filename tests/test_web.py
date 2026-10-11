from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from io import BytesIO

import pandas as pd
import psycopg
import pytest
from fastapi.testclient import TestClient
from helpers import make_catalog_item, make_snapshot

from vinted_tracker import db
from vinted_tracker.brand_lookup import BrandLookup
from vinted_tracker.web.app import create_app

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def make_client(conn, search=lambda kw: []):
    factory = lambda: nullcontext(conn)  # noqa: E731
    return TestClient(create_app(factory, BrandLookup(factory, search), clock=lambda: NOW))


@pytest.fixture
def client(conn):
    return make_client(conn)


def add_item(conn, item_id, title="Hanorac Nike", sold=False):
    uploaded = NOW - timedelta(days=2)
    db.insert_item(conn, item=make_catalog_item(item_id, title=title, price_ron=Decimal("100")),
                   snap=make_snapshot(item_id, price=Decimal("100")), query_name="q", uploaded_at=uploaded,
                   first_seen_at=uploaded, next_check_at=NOW + timedelta(hours=1))
    if sold:
        db.update_item_after_check(conn, item_id, checked_at=NOW, next_check_at=None, final_status="sold",
                                   sold_after_min=timedelta(hours=2), sold_after_max=timedelta(hours=4), uncertain=False)


def test_page_renders_on_empty_database(client):
    response = client.get("/")
    assert response.status_code == 200
    assert "Vinted tracker" in response.text and "Products" in response.text


def test_static_files_are_served(client):
    assert client.get("/static/htmx.min.js").status_code == 200
    assert client.get("/static/chart.umd.min.js").status_code == 200


def test_status_running_and_stopped(conn, client):
    assert "reported yet" in client.get("/fragments/status").text  # Jinja escapes the apostrophe in "hasn't"
    db.set_tracker_status(conn, {"health": "ok", "this_run": {"blocks": 0}}, NOW - timedelta(minutes=1))
    assert "Running" in client.get("/fragments/status").text
    db.set_tracker_status(conn, {"health": "ok"}, NOW - timedelta(minutes=30))
    assert "Tracker stopped" in client.get("/fragments/status").text


def test_tiles_show_counts(conn, client):
    add_item(conn, 1, sold=True)
    add_item(conn, 2)
    text = client.get("/fragments/tiles").text
    assert "Tracking" in text and "Sold" in text and ">1<" in text


def test_products_filter_by_status(conn, client):
    add_item(conn, 1, title="Sold hoodie", sold=True)
    add_item(conn, 2, title="Live hoodie")
    text = client.get("/fragments/products", params={"status": "sold"}).text
    assert "Sold hoodie" in text and "Live hoodie" not in text


def test_products_escape_html_in_titles(conn, client):
    add_item(conn, 1, title='<script>alert("x")</script>')
    text = client.get("/fragments/products").text
    assert "&lt;script&gt;" in text and "<script>alert" not in text


def test_charts_json(client):
    data = client.get("/api/charts").json()
    assert set(data) == {"brand", "type", "size", "price_band"}


def test_excel_download(conn, client):
    add_item(conn, 1, sold=True)
    response = client.get("/export.xlsx")
    assert response.status_code == 200
    assert response.headers["content-disposition"] == 'attachment; filename="vinted_report_2026-10-05.xlsx"'
    assert "Items" in pd.read_excel(BytesIO(response.content), sheet_name=None)


def test_database_down_shows_a_message():
    def broken():
        raise psycopg.OperationalError("connection refused")

    client = TestClient(create_app(broken, BrandLookup(broken, lambda kw: []), clock=lambda: NOW))
    assert client.get("/").status_code == 200
    assert "Can't reach the database" in client.get("/fragments/tiles").text
    assert "Can't reach the database" in client.get("/fragments/status").text
    assert client.get("/api/charts").status_code == 503


from helpers import make_settings  # noqa: E402

from vinted_tracker import watch_settings  # noqa: E402

VALID_FORM = {
    "group_key": ["g0"], "group_name_g0": "Streetwear", "brand_g0": ["53|Nike", "14|adidas"],
    "catalog_ids": ["76", "79"], "size_ids": ["208"], "status_ids": ["6", "1"],
}


def test_settings_panel_without_settings(client):
    assert "Start the tracker once" in client.get("/fragments/settings").text


def test_settings_panel_shows_current_settings(conn, client):
    watch_settings.save(conn, make_settings(), NOW)
    text = client.get("/fragments/settings").text
    assert 'value="streetwear"' in text and "Nike" in text
    assert 'name="catalog_ids" value="76" checked' in text
    assert 'name="catalog_ids" value="257" checked' not in text


def test_saving_valid_settings(conn, client):
    watch_settings.save(conn, make_settings(), NOW)
    text = client.post("/settings", data=VALID_FORM).text
    assert "Saved" in text
    version, s = watch_settings.load(conn)
    assert version == 2
    assert [b.title for b in s.groups[0].brands] == ["Nike", "adidas"] and s.size_ids == (208,)


def test_invalid_settings_are_refused_and_kept_in_the_form(conn, client):
    watch_settings.save(conn, make_settings(), NOW)
    form = dict(VALID_FORM, catalog_ids=[])
    text = client.post("/settings", data=form).text
    assert "Pick at least one product type." in text
    assert 'value="Streetwear"' in text  # what the user typed is not lost
    assert watch_settings.load(conn)[0] == 1


def test_brand_search_results(conn):
    client = make_client(conn, search=lambda kw: [{"id": 362, "title": "Carhartt", "item_count": 4087187}])
    text = client.get("/brands/search", params={"brand_q": "carhartt", "group": "g0"}).text
    assert 'data-id="362"' in text and 'data-group="g0"' in text and "4,087,187" in text


def test_brand_results_escape_titles(conn):
    client = make_client(conn, search=lambda kw: [{"id": 1, "title": '"><img src=x>', "item_count": 1}])
    text = client.get("/brands/search", params={"brand_q": "xx", "group": "g0"}).text
    assert "<img src=x>" not in text


def test_brand_search_failure_message(conn):
    def failing(kw):
        raise RuntimeError("challenge")

    text = make_client(conn, search=failing).get("/brands/search", params={"brand_q": "nike", "group": "g0"}).text
    assert "answer, try again in a few minutes" in text  # the apostrophe in "didn't" is HTML-escaped


def test_brand_search_no_results(conn):
    text = make_client(conn).get("/brands/search", params={"brand_q": "zzzz", "group": "g0"}).text
    assert "No brand called" in text


def test_enter_in_brand_search_does_not_submit_the_form(conn, client):
    watch_settings.save(conn, make_settings(), NOW)
    text = client.get("/fragments/settings").text
    assert "if (event.key === 'Enter') event.preventDefault()" in text
