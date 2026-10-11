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
