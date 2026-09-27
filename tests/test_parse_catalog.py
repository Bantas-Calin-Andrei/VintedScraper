from decimal import Decimal

import pytest
from helpers import catalog_entry, catalog_html, make_html, rsc_row

from vinted_tracker.parse import ParseError, parse_catalog, rsc_text


def test_rsc_text_joins_chunks_split_mid_row():
    rows = [rsc_row("1", {"a": "ă ș"}), rsc_row("2", [1, 2, 3])]
    assert rsc_text(make_html(*rows)) == "".join(r + "\n" for r in rows)


def test_parse_catalog_reads_items_in_order():
    html = catalog_html(
        catalog_entry(300, brand="Stone Island", size="L", condition="Bună", price="91.51"),
        catalog_entry(299, brand="Nike", size="M", condition="Foarte bună", price="80.0"),
    )
    items = parse_catalog(html)
    assert [i.id for i in items] == [300, 299]
    first = items[0]
    assert first.brand == "Stone Island"
    assert first.size == "L"
    assert first.condition == "Bună"
    assert first.price_ron == Decimal("91.51")
    assert first.favourite_count == 2
    assert first.seller_id == 99
    assert first.url == "/items/300-hanorac"
    assert first.raw["productItem"]["id"] == 300


def test_parse_catalog_dedupes_and_skips_rows_that_are_not_json():
    html = make_html(
        '1:I["123",["chunk.js"],"Catalog"]',
        '2:"$Sreact.suspense"',
        "3:T12,hello world!",
        rsc_row("4", {"items": {"items": [catalog_entry(5), catalog_entry(5), {"id": 6}]}}),
    )
    assert [i.id for i in parse_catalog(html)] == [5]


def test_parse_catalog_without_items_raises():
    with pytest.raises(ParseError):
        parse_catalog(make_html(rsc_row("1", {"nothing": "here"})))


def test_item_without_label_has_no_brand():
    entry = catalog_entry(7)
    del entry["productItem"]["itemBox"]
    (item,) = parse_catalog(catalog_html(entry))
    assert (item.brand, item.size, item.condition) == (None, None, None)
