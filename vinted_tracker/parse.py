"""Turn rendered vinted.ro pages into typed records.

This is the ONLY module that knows how Vinted structures its pages. Data comes
from the Next.js payload embedded in each page as `self.__next_f.push([1, "<chunk>"])`
scripts. The chunks join into newline-separated rows `<id>:<json>`.
"""
from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any, Iterator

from .models import CatalogItem


class ParseError(ValueError):
    """The page did not have the structure we expect. Vinted may have changed something."""


_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,\s*("(?:[^"\\]|\\.)*")\]\)', re.S)
_LABEL_RES = {
    "brand": re.compile(r"Brand:\s*([^,]+)"),
    "condition": re.compile(r"Stare:\s*([^,]+)"),
    "size": re.compile(r"Mărime:\s*([^,]+)"),
}
_LABEL_HINT = re.compile(r"(Brand|Stare|Mărime):")


def rsc_text(html: str) -> str:
    """Join all payload chunks of a page into one string."""
    parts = []
    for match in _PUSH_RE.finditer(html):
        try:
            parts.append(json.loads(match.group(1)))
        except json.JSONDecodeError:
            continue
    return "".join(parts)


def iter_json_values(rsc: str) -> Iterator[Any]:
    """Yield every payload row whose value is a JSON object or array."""
    for line in rsc.split("\n"):
        colon = line.find(":")
        if colon < 0:
            continue
        payload = line[colon + 1 :]
        if not payload or payload[0] not in "[{":
            continue
        try:
            yield json.loads(payload)
        except json.JSONDecodeError:
            continue


def iter_dicts(node: Any) -> Iterator[dict]:
    """Depth-first, document-order walk over every dict inside `node`."""
    stack = [node]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            yield current
            stack.extend(reversed(list(current.values())))
        elif isinstance(current, list):
            stack.extend(reversed(current))


def all_dicts(html: str) -> list[dict]:
    found: list[dict] = []
    for value in iter_json_values(rsc_text(html)):
        found.extend(iter_dicts(value))
    return found


def parse_catalog(html: str) -> list[CatalogItem]:
    entries = None
    for d in all_dicts(html):
        inner = d.get("items")
        if (
            isinstance(inner, dict)
            and isinstance(inner.get("items"), list)
            and any(isinstance(e, dict) and "productItem" in e for e in inner["items"])
        ):
            entries = inner["items"]
            break
    if entries is None:
        raise ParseError("catalog: no items list found in page data")

    items: list[CatalogItem] = []
    seen: set[int] = set()
    for entry in entries:
        product = entry.get("productItem") if isinstance(entry, dict) else None
        if not isinstance(product, dict) or _int(product.get("id")) is None:
            continue
        item_id = int(product["id"])
        if item_id in seen:
            continue
        seen.add(item_id)
        amount, currency = _money(product.get("price"))
        label = _label_text(entry)
        items.append(
            CatalogItem(
                id=item_id,
                title=str(product.get("title") or ""),
                url=str(product.get("url") or f"/items/{item_id}"),
                price_ron=amount if currency == "RON" else None,
                favourite_count=_int(product.get("favouriteCount")),
                seller_id=_int((product.get("user") or {}).get("id")),
                brand=_label_field(label, "brand"),
                size=_label_field(label, "size"),
                condition=_label_field(label, "condition"),
                raw=entry,
            )
        )
    return items


def _label_text(entry: dict) -> str:
    for d in iter_dicts(entry):
        for value in d.values():
            if isinstance(value, str) and _LABEL_HINT.search(value):
                return value
    return ""


def _label_field(label: str, key: str) -> str | None:
    match = _LABEL_RES[key].search(label)
    return match.group(1).strip() if match else None


def _money(value: Any) -> tuple[Decimal | None, str | None]:
    if not isinstance(value, dict):
        return None, None
    amount = value.get("amount")
    currency = value.get("currencyCode") or value.get("currency_code")
    try:
        parsed = Decimal(str(amount)) if amount is not None else None
    except InvalidOperation:
        parsed = None
    return parsed, (str(currency) if currency else None)


def _int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
