"""Shared test helpers: synthetic Vinted pages, fixture loading, fakes."""
from __future__ import annotations

import gzip
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from vinted_tracker.config import Config, Query
from vinted_tracker.models import CatalogItem, FetchedPage, ItemSnapshot, Status

FIXTURES = Path(__file__).resolve().parent / "fixtures"
BASE = "https://www.vinted.ro"


def rsc_row(row_id: str, value: Any) -> str:
    return f"{row_id}:{json.dumps(value, ensure_ascii=False)}"


def make_html(*rows: str) -> str:
    """Build a page whose Next.js payload holds `rows`, split mid-row across two pushes like real pages."""
    rsc = "".join(row + "\n" for row in rows)
    mid = len(rsc) // 2
    scripts = "".join(
        f"<script>self.__next_f.push([1,{json.dumps(part)}])</script>" for part in (rsc[:mid], rsc[mid:])
    )
    return f"<!DOCTYPE html><html><body><script>self.__next_f.push([0])</script>{scripts}</body></html>"


def catalog_entry(item_id: int, *, brand="Nike", size="M", condition="Foarte bună", price="80.0", title=None) -> dict:
    title = title or f"Hanorac {item_id}"
    return {
        "id": item_id,
        "productItem": {
            "id": item_id,
            "title": title,
            "url": f"/items/{item_id}-hanorac",
            "favouriteCount": 2,
            "price": {"amount": price, "currencyCode": "RON"},
            "user": {"id": 99, "isBusiness": False},
            "itemBox": {
                "accessibilityLabel": f"{title}, Brand: {brand}, Stare: {condition}, Mărime: {size}, {price} lei, 99.00 lei"
            },
        },
        "catalogTracking": {"contentSource": "catalog"},
    }


def catalog_html(*entries: dict) -> str:
    return make_html(
        rsc_row("0", {"buildId": "x"}),
        '1:I["123",["chunk.js"],"Catalog"]',
        rsc_row("2", ["$", "$L1", None, {"catalog": {"items": {"items": list(entries)}}}]),
    )


def catalog_page(url: str, ids: list[int], **entry_kw) -> FetchedPage:
    return FetchedPage(url=url, status=200, html=catalog_html(*(catalog_entry(i, **entry_kw) for i in ids)), text="")


def item_page(
    item_id: int = 555,
    *,
    can_buy: bool = True,
    is_reserved: bool = False,
    is_hidden: bool = False,
    currency: str = "RON",
    amount: str = "120.0",
    text: str = "Încărcat acum 3 minute",
    status: int = 200,
    url: str | None = None,
) -> FetchedPage:
    plugins = [
        {"name": "make_offer", "data": {"price": {"amount": amount, "currency_code": currency}, "seller_id": "7", "title": "Geacă"}},
        {
            "name": "ask_seller",
            "data": {
                "can_buy": can_buy,
                "instant_buy": can_buy,
                "is_hidden": is_hidden,
                "is_reserved": is_reserved,
                "item_id": str(item_id),
                "reservation": None,
                "seller_id": "7",
            },
        },
        {"name": "attributes", "data": {"catalog_id": "1803", "favourite_count": 4}},
    ]
    html = make_html(rsc_row("a", ["$", "div", None, {"plugins": plugins}]))
    return FetchedPage(url=url or f"{BASE}/items/{item_id}-geaca", status=status, html=html, text=text)


def load_fixture(name: str, directory: Path = FIXTURES) -> FetchedPage:
    meta = json.loads((directory / f"{name}.meta.json").read_text(encoding="utf-8"))
    html = gzip.decompress((directory / f"{name}.html.gz").read_bytes()).decode("utf-8")
    text = (directory / f"{name}.txt").read_text(encoding="utf-8")
    return FetchedPage(url=meta["url"], status=meta["status"], html=html, text=text)


def load_expected(directory: Path = FIXTURES) -> dict | None:
    path = directory / "expected.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def make_config(**overrides) -> Config:
    values = dict(
        base_url=BASE,
        queries=(Query("streetwear", (5,), (53,)),),
        poll_minutes=5.0,
        max_item_age_minutes=60.0,
        max_new_per_day=250,
        whole_price_prefilter=True,
        recheck_schedule=((24.0, 2.0), (168.0, 8.0), (720.0, 24.0)),
        uncertain_gap_hours=48.0,
        min_delay_s=8.0,
        max_delay_s=12.0,
        max_pages_per_hour=360,
        backoff_minutes=(30.0, 60.0, 120.0, 240.0),
        headless=True,
        database_url="postgresql://unused",
    )
    values.update(overrides)
    return Config(**values)


def make_catalog_item(item_id: int = 1001, **overrides) -> CatalogItem:
    values = dict(
        id=item_id,
        title="Hanorac Nike",
        url=f"/items/{item_id}-hanorac-nike",
        price_ron=Decimal("80.00"),
        favourite_count=0,
        seller_id=7,
        brand="Nike",
        size="M",
        condition="Foarte bună",
        raw={"productItem": {"id": item_id}},
    )
    values.update(overrides)
    return CatalogItem(**values)


def make_snapshot(item_id: int = 1001, **overrides) -> ItemSnapshot:
    values = dict(
        item_id=item_id,
        status=Status.AVAILABLE,
        price=Decimal("80.00"),
        currency="RON",
        favourite_count=1,
        catalog_id=1803,
        upload_age=timedelta(minutes=5),
        raw={"buy": {"can_buy": True}},
    )
    values.update(overrides)
    return ItemSnapshot(**values)


class FakeFetcher:
    def __init__(self, pages: dict[str, FetchedPage] | None = None) -> None:
        self.pages = dict(pages or {})
        self.calls: list[str] = []
        self.pages_loaded = 0

    def fetch(self, url: str) -> FetchedPage:
        self.calls.append(url)
        if url not in self.pages:
            raise AssertionError(f"unexpected fetch: {url}")
        self.pages_loaded += 1
        return self.pages[url]


class BlockingFetcher:
    pages_loaded = 0

    def fetch(self, url: str) -> FetchedPage:
        from vinted_tracker.browser import BlockedError

        raise BlockedError(f"challenge at {url}")
