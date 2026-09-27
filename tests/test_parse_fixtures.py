from decimal import Decimal

import pytest
from helpers import load_expected, load_fixture

from vinted_tracker.parse import parse_catalog, parse_item, parse_upload_age

EXPECTED = load_expected()
needs_fixtures = pytest.mark.skipif(EXPECTED is None, reason="real page fixtures are captured in Task 8")


@needs_fixtures
def test_catalog_fixture():
    spec = EXPECTED["catalog"]
    items = parse_catalog(load_fixture(spec["file"]).html)
    assert len(items) >= spec["min_items"]
    first = items[0]
    for key in ("id", "brand", "size", "condition"):
        assert getattr(first, key) == spec["first_item"][key]
    assert first.price_ron == Decimal(spec["first_item"]["price_ron"])


@needs_fixtures
@pytest.mark.parametrize("case", (EXPECTED or {}).get("items", []), ids=lambda c: c["file"])
def test_item_fixture(case):
    page = load_fixture(case["file"])
    snap = parse_item(page, case["item_id"])
    assert snap.status.value == case["status"]
    if "currency" in case:
        assert snap.currency == case["currency"]
    if "price" in case:
        assert snap.price == Decimal(case["price"])
    if "upload_age_minutes" in case:
        assert parse_upload_age(page.text).total_seconds() / 60 == case["upload_age_minutes"]
