"""One polite Playwright session: rate limited, light (no images/ads), and stops when challenged."""
from __future__ import annotations

import logging
import random
import time
from collections import deque
from pathlib import Path
from typing import Callable, Protocol

from .models import FetchedPage, utcnow

log = logging.getLogger(__name__)

CHALLENGE_MARKERS = ("captcha-delivery.com",)
BLOCKED_STATUSES = frozenset({403, 429})
BLOCKED_RESOURCE_TYPES = frozenset({"image", "media", "font"})
BLOCKED_HOST_PARTS = (
    "doubleclick", "googlesyndication", "googletagservices", "adservice", "amazon-adsystem",
    "rubiconproject", "smartadserver", "connectad", "id5-sync", "criteo", "pubmatic",
    "taboola", "adnxs", "casalemedia", "openx",
)


class BlockedError(RuntimeError):
    """Vinted served a challenge or refused access. The caller must stop and back off."""


class FetchError(RuntimeError):
    """The page could not be loaded after retries."""


class Fetcher(Protocol):
    pages_loaded: int

    def fetch(self, url: str) -> FetchedPage: ...


def is_challenge(status: int, html: str) -> bool:
    return status in BLOCKED_STATUSES or any(marker in html for marker in CHALLENGE_MARKERS)


def should_block(resource_type: str, url: str) -> bool:
    return resource_type in BLOCKED_RESOURCE_TYPES or any(part in url for part in BLOCKED_HOST_PARTS)


class RateLimiter:
    """Random gap between page loads plus a cap on pages in any rolling hour."""

    def __init__(
        self,
        min_delay_s: float,
        max_delay_s: float,
        max_per_hour: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        rand: Callable[[float, float], float] = random.uniform,
    ) -> None:
        self._min, self._max, self._max_per_hour = min_delay_s, max_delay_s, max_per_hour
        self._clock, self._sleep, self._rand = clock, sleep, rand
        self._last: float | None = None
        self._recent: deque[float] = deque()

    def wait(self) -> None:
        now = self._clock()
        if self._last is not None:
            remaining = self._last + self._rand(self._min, self._max) - now
            if remaining > 0:
                self._sleep(remaining)
                now = self._clock()
        self._forget_older_than_an_hour(now)
        if len(self._recent) >= self._max_per_hour:
            self._sleep(3600 - (now - self._recent[0]))
            now = self._clock()
            self._forget_older_than_an_hour(now)
        self._last = now
        self._recent.append(now)

    def _forget_older_than_an_hour(self, now: float) -> None:
        while self._recent and now - self._recent[0] >= 3600:
            self._recent.popleft()


class BrowserSession:
    """Context manager around one persistent Chromium profile."""

    def __init__(
        self,
        profile_dir: Path,
        limiter: RateLimiter,
        *,
        headless: bool = True,
        retries: int = 3,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._profile_dir, self._limiter = profile_dir, limiter
        self._headless, self._retries, self._sleep = headless, retries, sleep
        self.pages_loaded = 0

    def __enter__(self) -> "BrowserSession":
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        self._ctx = self._pw.chromium.launch_persistent_context(
            str(self._profile_dir),
            headless=self._headless,
            locale="ro-RO",
            timezone_id="Europe/Bucharest",
            viewport={"width": 1366, "height": 900},
        )
        self._ctx.route("**/*", self._route)
        self._page = self._ctx.pages[0] if self._ctx.pages else self._ctx.new_page()
        return self

    def __exit__(self, *exc_info) -> None:
        self._ctx.close()
        self._pw.stop()

    @staticmethod
    def _route(route) -> None:
        request = route.request
        if should_block(request.resource_type, request.url):
            route.abort()
        else:
            route.continue_()

    def fetch(self, url: str) -> FetchedPage:
        from playwright.sync_api import Error as PlaywrightError

        last_error: Exception | None = None
        for attempt in range(self._retries):
            self._limiter.wait()
            try:
                response = self._page.goto(url, wait_until="load", timeout=45_000)
                self.pages_loaded += 1
                status = response.status if response else 0
                html = self._page.content()
                text = self._page.inner_text("body")
            except PlaywrightError as exc:
                last_error = exc
                log.warning("load failed (%s/%s) %s: %s", attempt + 1, self._retries, url, exc)
                self._sleep(5 * 2**attempt)
                continue
            if is_challenge(status, html):
                raise BlockedError(f"challenge or refusal at {url} (HTTP {status})")
            return FetchedPage(url=self._page.url, status=status, html=html, text=text)
        raise FetchError(f"failed to load {url} after {self._retries} attempts: {last_error}")


def save_debug_page(page: FetchedPage, label: str, debug_dir: Path) -> Path:
    """Keep a page that failed to parse so the parser can be fixed later."""
    debug_dir.mkdir(parents=True, exist_ok=True)
    stamp = utcnow().strftime("%Y%m%dT%H%M%S")
    html_path = debug_dir / f"{stamp}-{label}.html"
    html_path.write_text(page.html, encoding="utf-8")
    html_path.with_suffix(".txt").write_text(
        f"URL: {page.url}\nHTTP: {page.status}\n\n{page.text}", encoding="utf-8"
    )
    return html_path
