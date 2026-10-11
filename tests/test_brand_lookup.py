from contextlib import nullcontext
from datetime import datetime, timedelta, timezone

import pytest

from vinted_tracker import db
from vinted_tracker.brand_lookup import BrandLookup, LookupFailed

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
NIKE = [{"id": 53, "title": "Nike", "item_count": 100}]


class FakeSearch:
    def __init__(self, result=None, error=None):
        self.calls, self.result, self.error = [], result or NIKE, error

    def __call__(self, keyword):
        self.calls.append(keyword)
        if self.error:
            raise self.error
        return self.result


def make(conn, search, now=NOW, sleeps=None):
    return BrandLookup(lambda: nullcontext(conn), search, clock=lambda: now,
                       sleep=(sleeps.append if sleeps is not None else lambda s: None), monotonic=lambda: 1000.0)


def test_first_search_asks_vinted_then_uses_the_cache(conn):
    search = FakeSearch()
    lookup = make(conn, search)
    assert lookup.search(" Nike ") == NIKE
    assert lookup.search("nike") == NIKE
    assert search.calls == ["nike"]
    assert db.get_brand_cache(conn, "nike") == (NIKE, NOW)


def test_old_cache_is_refreshed(conn):
    db.put_brand_cache(conn, "nike", [{"id": 1, "title": "Old", "item_count": 0}], NOW - timedelta(days=31))
    search = FakeSearch()
    assert make(conn, search).search("nike") == NIKE
    assert search.calls == ["nike"]


def test_short_keywords_do_not_search(conn):
    search = FakeSearch()
    assert make(conn, search).search("n") == []
    assert search.calls == []


def test_failure_gives_a_friendly_message(conn):
    lookup = make(conn, FakeSearch(error=RuntimeError("challenge")))
    with pytest.raises(LookupFailed, match="Vinted didn't answer"):
        lookup.search("nike")
    assert db.get_brand_cache(conn, "nike") is None


def test_searches_are_spaced_out(conn):
    sleeps = []
    lookup = make(conn, FakeSearch(), sleeps=sleeps)
    lookup.search("nike")
    lookup.search("adidas")
    assert sleeps == [5.0]
