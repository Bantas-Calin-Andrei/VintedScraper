"""Plain data types shared across the tracker."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum


class Status(StrEnum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    SOLD = "sold"
    HIDDEN = "hidden"
    DELETED = "deleted"
    UNKNOWN = "unknown"


UNSOLD_FINAL = "unsold_30d"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class FetchedPage:
    url: str  # final URL after redirects
    status: int  # HTTP status of the main document, 0 if unknown
    html: str
    text: str  # visible body text


@dataclass(frozen=True)
class CatalogItem:
    id: int
    title: str
    url: str
    price_ron: Decimal | None
    favourite_count: int | None
    seller_id: int | None
    brand: str | None
    size: str | None
    condition: str | None
    raw: dict = field(repr=False, compare=False)


@dataclass(frozen=True)
class ItemSnapshot:
    item_id: int
    status: Status
    price: Decimal | None  # in `currency` (the seller's own currency)
    currency: str | None
    favourite_count: int | None
    catalog_id: int | None
    upload_age: timedelta | None
    raw: dict = field(repr=False, compare=False)
