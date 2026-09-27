from datetime import timedelta
from decimal import Decimal

import pytest
from helpers import BASE, item_page, make_html, rsc_row

from vinted_tracker.models import FetchedPage, Status
from vinted_tracker.parse import ParseError, parse_item, parse_upload_age


def test_available_romanian_item():
    snap = parse_item(item_page(555), 555)
    assert snap.status is Status.AVAILABLE
    assert snap.price == Decimal("120.0")
    assert snap.currency == "RON"
    assert snap.favourite_count == 4
    assert snap.catalog_id == 1803
    assert snap.upload_age == timedelta(minutes=3)
    assert snap.raw["buy"]["can_buy"] is True


def test_foreign_seller_currency():
    assert parse_item(item_page(555, currency="PLN", amount="150"), 555).currency == "PLN"


def test_reserved():
    assert parse_item(item_page(555, can_buy=False, is_reserved=True), 555).status is Status.RESERVED


def test_sold():
    page = item_page(555, can_buy=False, text="Vândut\nÎncărcat acum 2 zile")
    assert parse_item(page, 555).status is Status.SOLD


def test_hidden():
    assert parse_item(item_page(555, can_buy=False, is_hidden=True), 555).status is Status.HIDDEN


def test_buyable_item_with_sold_word_elsewhere_stays_available():
    page = item_page(555, text="Încărcat acum 3 minute\nArticole similare\nVândut")
    assert parse_item(page, 555).status is Status.AVAILABLE


def test_not_buyable_without_any_signal_is_unknown():
    assert parse_item(item_page(555, can_buy=False), 555).status is Status.UNKNOWN


def test_http_404_is_deleted():
    page = FetchedPage(url=f"{BASE}/items/555", status=404, html="<html></html>", text="")
    snap = parse_item(page, 555)
    assert snap.status is Status.DELETED
    assert snap.raw == {"http_status": 404, "final_url": f"{BASE}/items/555"}


def test_redirect_away_from_item_is_deleted():
    page = FetchedPage(url=f"{BASE}/catalog", status=200, html="<html></html>", text="")
    assert parse_item(page, 555).status is Status.DELETED


def test_redirect_to_other_item_with_same_prefix_is_deleted():
    page = FetchedPage(url=f"{BASE}/items/5551-alt", status=200, html="<html></html>", text="")
    assert parse_item(page, 555).status is Status.DELETED


def test_missing_buy_state_raises():
    page = FetchedPage(url=f"{BASE}/items/555-x", status=200, html=make_html(rsc_row("1", {"x": 1})), text="")
    with pytest.raises(ParseError):
        parse_item(page, 555)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Încărcat acum 3 minute", timedelta(minutes=3)),
        ("Încărcat\nacum 3 minute", timedelta(minutes=3)),
        ("Încărcat acum 25 de minute", timedelta(minutes=25)),
        ("Încărcat acum un minut", timedelta(minutes=1)),
        ("Încărcat acum câteva secunde", timedelta(seconds=3)),
        ("Încărcat acum o oră", timedelta(hours=1)),
        ("Încărcat acum 2 ore", timedelta(hours=2)),
        ("Încărcat acum o zi", timedelta(days=1)),
        ("Încărcat acum 3 zile", timedelta(days=3)),
        ("Încărcat acum o săptămână", timedelta(days=7)),
        ("Încărcat acum 2 săptămâni", timedelta(days=14)),
        ("Încărcat acum o lună", timedelta(days=30)),
        ("Încărcat acum 2 luni", timedelta(days=60)),
        ("Încărcat acum un an", timedelta(days=365)),
        ("Nimic relevant aici", None),
    ],
)
def test_parse_upload_age(text, expected):
    assert parse_upload_age(text) == expected
