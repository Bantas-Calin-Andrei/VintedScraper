"""Search Vinted's brand list for the settings panel (cached; one short-lived browser per lookup)."""
from __future__ import annotations

import logging
import threading
import time
from contextlib import AbstractContextManager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import psycopg

from . import db
from .browser import BlockedError, is_challenge
from .models import utcnow

log = logging.getLogger(__name__)
SearchFn = Callable[[str], list[dict]]
ConnFactory = Callable[[], AbstractContextManager[psycopg.Connection]]
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
        if len(key) < 2:
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
        with self._conn_factory() as conn:
            db.put_brand_cache(conn, key, results, self._clock())
        return results


def playwright_brand_search(profile_dir: Path, base_url: str) -> SearchFn:
    def search(keyword: str) -> list[dict]:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                str(profile_dir), headless=True, locale="ro-RO", timezone_id="Europe/Bucharest"
            )
            try:
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                response = page.goto(f"{base_url}/catalog", wait_until="domcontentloaded", timeout=45_000)
                if is_challenge(response.status if response else 0, page.content()):
                    raise BlockedError("challenge during brand lookup")
                data = page.evaluate(
                    """async (kw) => {
                        const r = await fetch('/api/v2/brands?keyword=' + encodeURIComponent(kw),
                                              {headers: {accept: 'application/json'}});
                        if (!r.ok) throw new Error('HTTP ' + r.status);
                        return await r.json();
                    }""",
                    keyword,
                )
            finally:
                ctx.close()
        return [
            {"id": int(b["id"]), "title": str(b["title"]), "item_count": int(b.get("item_count") or 0)}
            for b in (data.get("brands") or [])[:10]
        ]

    return search
