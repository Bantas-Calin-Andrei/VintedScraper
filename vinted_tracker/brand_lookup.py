"""Search Vinted's brand list for the settings panel (cached; one short-lived browser per lookup)."""
from __future__ import annotations

import logging
import threading
import time
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from typing import Callable

import psycopg

from . import db
from .browser import BlockedError, is_challenge
from .models import utcnow

log = logging.getLogger(__name__)
SearchFn = Callable[[str], list[dict]]
ConnFactory = Callable[[], AbstractContextManager[psycopg.Connection]]
MIN_KEYWORD_LENGTH = 3
FAILED_MESSAGE = "Vinted didn't answer, try again in a few minutes."


class LookupFailed(RuntimeError):
    pass


class BrandLookup:
    def __init__(
        self,
        conn_factory: ConnFactory,
        search: SearchFn,
        *,
        clock: Callable[[], datetime] = utcnow,
        min_interval_s: float = 5.0,
        cache_days: int = 30,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._conn_factory, self._search = conn_factory, search
        self._clock, self._min_interval_s, self._cache_age = clock, min_interval_s, timedelta(days=cache_days)
        self._sleep, self._monotonic = sleep, monotonic
        self._lock = threading.Lock()
        self._last: float | None = None

    def search(self, keyword: str) -> list[dict]:
        key = keyword.strip().casefold()
        if len(key) < MIN_KEYWORD_LENGTH:
            return []
        with self._conn_factory() as conn:
            cached = db.get_brand_cache(conn, key)
        if cached is not None and self._clock() - cached[1] < self._cache_age:
            return cached[0]
        with self._lock:
            if self._last is not None:
                wait = self._last + self._min_interval_s - self._monotonic()
                if wait > 0:
                    self._sleep(wait)
            try:
                results = self._search(key)
            except Exception as exc:
                log.warning("brand lookup for %r failed: %s", key, exc)
                raise LookupFailed(FAILED_MESSAGE) from exc
            finally:
                self._last = self._monotonic()
        if results:  # "no such brand" isn't remembered, so a brand Vinted adds later is still found
            with self._conn_factory() as conn:
                db.put_brand_cache(conn, key, results, self._clock())
        return results


def merge_brand_results(keyword: str, *result_lists: list[dict], limit: int = 10) -> list[dict]:
    """Combine brand lists without duplicates; an exact name match comes first, and known item counts win."""
    merged: dict[int, dict] = {}
    for results in result_lists:
        for brand in results:
            known = merged.get(brand["id"])
            if known is None:
                merged[brand["id"]] = dict(brand)
            elif not known["item_count"] and brand["item_count"]:
                known["item_count"] = brand["item_count"]
    key = keyword.strip().casefold()
    ordered = sorted(merged.values(), key=lambda b: b["title"].casefold() != key)  # stable: keeps list order
    return ordered[:limit]


def _brands(data: dict) -> list[dict]:
    return [
        {"id": int(b["id"]), "title": str(b["title"]), "item_count": int(b.get("item_count") or 0)}
        for b in (data.get("brands") or [])
    ]


def playwright_brand_search(base_url: str) -> SearchFn:
    """Each search uses a clean browser session: Vinted gives every new visitor a fresh anonymous token,
    whereas reused cookies hold an expired one and the brands API answers 401."""
    def search(keyword: str) -> list[dict]:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_context(locale="ro-RO", timezone_id="Europe/Bucharest").new_page()
                response = page.goto(f"{base_url}/catalog", wait_until="load", timeout=45_000)
                if is_challenge(response.status if response else 0, page.content()):
                    raise BlockedError("challenge during brand lookup")
                # Two lists: the public brand search (established brands, with item counts) and the
                # upload form's list, which also has small brands such as Vescartes.
                data = page.evaluate(
                    """async (kw) => {
                        const get = async (path) => {
                            const r = await fetch(path + encodeURIComponent(kw), {headers: {accept: 'application/json'}});
                            if (!r.ok) throw new Error('HTTP ' + r.status);
                            return await r.json();
                        };
                        return {
                            public: await get('/api/v2/brands?keyword='),
                            upload: await get('/api/v2/item_upload/brands?keyword='),
                        };
                    }""",
                    keyword,
                )
            finally:
                browser.close()
        return merge_brand_results(keyword, _brands(data["public"]), _brands(data["upload"]))

    return search
