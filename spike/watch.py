"""THROWAWAY spike (Phase 0). Not part of the tracker.

Watches the newest listings of one catalog URL on vinted.ro and saves a page
snapshot every time an item's buy state changes, so we can see exactly what
sold / reserved / deleted items look like in the page data.

Usage:
  .venv\\Scripts\\python spike\\watch.py "<catalog url>" [items=50] [hours=24] [--headed]
"""
from __future__ import annotations

import json
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path("spike/out")
ID_RE = re.compile(r"/items/(\d+)")
FLAG_RE = {k: re.compile(r'\\*"%s\\*":(true|false)' % k) for k in ("can_buy", "is_reserved", "is_hidden")}
CURRENCY_RE = re.compile(r'\\*"currency_code\\*":\\*"([A-Z]{3})')
CYCLE_S = 30 * 60
BLOCK_TYPES = {"image", "media", "font"}


def state(status: int, url: str, html: str, text: str, item_id: int) -> dict:
    s = {
        "http": status,
        "on_item_page": f"/items/{item_id}" in url,
        "sold_text": "Vândut" in text,
    }
    for key, rx in FLAG_RE.items():
        m = rx.search(html)
        s[key] = m.group(1) if m else None
    m = CURRENCY_RE.search(html)
    s["currency"] = m.group(1) if m else None
    return s


def save(base: Path, status: int, url: str, html: str, text: str) -> None:
    Path(f"{base}.html").write_text(html, encoding="utf-8")
    Path(f"{base}.txt").write_text(text, encoding="utf-8")
    Path(f"{base}.meta.json").write_text(json.dumps({"url": url, "status": status}), encoding="utf-8")


def main() -> None:
    headed = "--headed" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--headed"]
    catalog_url = args[0]
    n = int(args[1]) if len(args) > 1 else 50
    hours = float(args[2]) if len(args) > 2 else 24.0
    OUT.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            "spike/profile", headless=not headed, locale="ro-RO", timezone_id="Europe/Bucharest"
        )
        ctx.route("**/*", lambda r: r.abort() if r.request.resource_type in BLOCK_TYPES else r.continue_())
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def get(url: str) -> tuple[int, str, str, str]:
            time.sleep(random.uniform(8, 12))
            resp = page.goto(url, wait_until="load", timeout=45_000)
            return (resp.status if resp else 0), page.url, page.content(), page.inner_text("body")

        status, url, html, text = get(catalog_url)
        save(OUT / "catalog", status, url, html, text)
        if status in (403, 429) or "captcha-delivery.com" in html:
            sys.exit("Blocked on the catalog page. Re-run with --headed and tell the user.")

        ids = list(dict.fromkeys(int(m) for m in ID_RE.findall(html)))[:n]
        print(f"watching {len(ids)} items for {hours} h", flush=True)
        last: dict[int, dict] = {}
        end = time.time() + hours * 3600
        while time.time() < end:
            cycle_start = time.time()
            for item_id in ids:
                status, url, html, text = get(f"https://www.vinted.ro/items/{item_id}")
                if status in (403, 429) or "captcha-delivery.com" in html:
                    print("BLOCKED - stopping spike", flush=True)
                    ctx.close()
                    return
                s = state(status, url, html, text, item_id)
                if last.get(item_id) != s:
                    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                    save(OUT / f"{item_id}-{stamp}", status, url, html, text)
                    with (OUT / "changes.jsonl").open("a", encoding="utf-8") as f:
                        f.write(json.dumps({"id": item_id, "at": stamp, "url": url, **s}) + "\n")
                    print(stamp, item_id, s, flush=True)
                    last[item_id] = s
            time.sleep(max(0.0, CYCLE_S - (time.time() - cycle_start)))
        ctx.close()


if __name__ == "__main__":
    main()
