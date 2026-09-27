# Vinted Sell-Time Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Python tool that finds brand-new men's listings from Romanian sellers on vinted.ro, re-checks each one until it sells (or 30 days pass), stores everything in PostgreSQL, and exports an Excel report of time-to-sell by brand, category, size, condition and price band.

**Architecture:** One long-running process drives one Playwright Chromium session at a polite, rate-limited pace. Pages are rendered by the browser, and structured data is read from the Next.js payload embedded in each page (`self.__next_f.push(...)` chunks). A scheduler loop alternates between discovery (newest-first catalog per watchlist query) and rechecks (a thinning schedule per item). All state lives in PostgreSQL, so restarts are safe.

**Tech Stack:** Python 3.13, Playwright (sync API, Chromium), psycopg 3, PostgreSQL 18, PyYAML, python-dotenv, pandas + openpyxl, pytest.

**Spec:** `docs/superpowers/specs/2026-09-27-vinted-sell-time-tracker-design.md`

## Global Constraints

- Platform: Windows 11, PowerShell. Every command below is PowerShell and runs from the repo root `C:\Users\calin\Desktop\VintedScraper`. Python is always `.venv\Scripts\python`.
- Python ≥ 3.12 (developed on 3.13). All datetimes are timezone-aware UTC (`datetime.now(timezone.utc)`), and nothing naive is ever stored.
- Market: `https://www.vinted.ro`, men's clothing root catalog `5`. Romanian seller = the item page's original price currency is `RON`.
- New listing = upload age at discovery **< 60 minutes**, and item ID above the query's high-water mark.
- Recheck schedule `[[24, 2], [168, 8], [720, 24]]` (age below N hours → check every M hours). The last row's age (720 h = 30 days) is where tracking stops with `unsold_30d`.
- Sold interval with a gap of more than **48 h** between last-live and first-sold → `uncertain`.
- Rate limit: random **8–12 s** gap between page loads, at most **360 pages/hour**. Images, media, fonts and ad hosts are blocked.
- Daily cap: **250** newly tracked items per rolling 24 h.
- **Never solve captchas or evade bot protection.** On a challenge (HTTP 403/429 or a `captcha-delivery.com` page), stop and back off 30 → 60 → 120 → 240 min (capped at 240).
- Database: PostgreSQL via `DATABASE_URL`. Tests use `TEST_DATABASE_URL` (database `vinted_tracker_test`). `.env` is git-ignored and never committed. `.env.example` is committed.
- Every commit message ends with the line `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>` (shown once here, and implied for every commit step below).
- Progress page: the controller (main session) updates https://claude.ai/artifact/5TZhDzeGjVt8wVTDqWcpj3 as described in "Progress page updates" at the end of every task. Sub-agents skip that step.

## Deviations from the spec (intentional, small)

1. **Romanian-seller check:** the catalog has no seller-country field (probe 2026-09-27: `user` has only `id, photo, thumbnailUrl, isBusiness`). The check happens on the first item-page visit. A cheap pre-filter (`discovery.whole_price_prefilter`) skips catalog prices with decimals, because foreign prices are currency-converted (for example `91.51 lei`). Task 8 measures whether the pre-filter is safe and turns it off if not.
2. Two helper tables, `skipped_items` (so rejected items are never re-fetched) and `query_state` (per-query high-water mark and last poll time).
3. The original price and currency live in `items.raw_first` (JSONB) rather than separate columns, since only RON items are stored.
4. `hidden` is not final immediately (sellers un-hide). It becomes the final status only if still hidden at 30 days.

## Review Focus

1. **A deleted listing redirects instead of returning 404.** The tracker must record `deleted`, not crash or loop. → Task 5 `test_redirect_away_from_item_is_deleted`.
2. **Upload-age wording varies** ("acum 25 de minute", "acum o oră", "câteva secunde", missing text). Wrong parsing would track old listings or drop new ones. → Task 5 `test_parse_upload_age` (parametrised).
3. **The PC was off for a day.** Overdue items must be processed oldest-first, and a long gap must make the sell time `uncertain` rather than wrong. → Task 3 `test_due_items_oldest_first_and_excludes_final`, Task 6 `test_long_gap_is_uncertain`.
4. **The same item shows up in two queries, or was already rejected.** It must never be tracked twice or re-fetched. → Task 9 `test_known_items_are_not_refetched`.
5. **"Vândut" (sold) appears elsewhere on a live item page** (for example a "similar items" block). A buyable item must stay `available`. → Task 5 `test_buyable_item_with_sold_word_elsewhere_stays_available`.

## File Structure

```
VintedScraper/
├─ pyproject.toml              package + deps + pytest config            (Task 2)
├─ config.yaml                 watchlist + tuning                         (Task 1)
├─ .env.example                DATABASE_URL / TEST_DATABASE_URL template  (Task 2)
├─ vinted_tracker/
│  ├─ __init__.py                                                         (Task 2)
│  ├─ models.py                Status, FetchedPage, CatalogItem, ItemSnapshot, utcnow  (Task 2)
│  ├─ config.py                load/validate config.yaml + env            (Task 2)
│  ├─ db.py                    schema + all SQL                           (Task 3)
│  ├─ parse.py                 page payload → CatalogItem / ItemSnapshot  (Tasks 4–5)
│  ├─ schedule.py              recheck intervals, stretch                 (Task 6)
│  ├─ outcome.py               sold / deleted / unsold decision           (Task 6)
│  ├─ browser.py               RateLimiter, BrowserSession, challenge detection (Task 7)
│  ├─ discover.py              catalog polling → tracked items            (Task 9)
│  ├─ recheck.py               item rechecks → observations/outcomes      (Task 10)
│  ├─ export.py                SQL summaries → Excel                      (Task 11)
│  ├─ runner.py                main loop, backoff, status.json            (Task 12)
│  └─ __main__.py              CLI: run, init-db, status, export, probe   (Task 12)
├─ tests/
│  ├─ conftest.py              `conn` fixture (test DB)                    (Task 2)
│  ├─ helpers.py               synthetic pages, fakes, fixture loader     (Task 2)
│  ├─ fixtures/                real captured pages + expected.json        (Task 8)
│  └─ test_*.py
├─ spike/                      THROWAWAY Phase 0 scripts                   (Tasks 1, 8)
├─ docs/spike-findings.md                                                 (Task 8)
├─ scripts/run_tracker.ps1, scripts/register_task.ps1                     (Task 13)
├─ Dockerfile, docker-compose.yml, README.md                              (Task 13)
```

Order: Task 1 starts a 24-hour spike in the background. Tasks 2–7 need no spike data. **Task 8 starts only when the spike has run ≥ 24 h.** Tasks 9–13 follow.

---

### Task 1: Phase 0 spike start + watchlist config (THROWAWAY spike code)

**Files:**
- Create: `spike/watch.py`, `spike/make_fixture.py`, `spike/prefilter_check.py`, `config.yaml`
- Modify: `.gitignore`

**Interfaces:**
- Produces: `spike/out/` snapshots (`<id>-<stamp>.html/.txt/.meta.json`, `catalog.*`, `changes.jsonl`) consumed by Task 8; `config.yaml` consumed by Task 2 onward.

- [ ] **Step 1: Create the virtual environment and install Playwright**

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install --upgrade pip
.venv\Scripts\python -m pip install playwright
.venv\Scripts\python -m playwright install chromium
```
Expected: the last command downloads Chromium with no error.

- [ ] **Step 2: Extend `.gitignore`**

Append these lines to `.gitignore`:
```
spike/out/
spike/profile/
logs/
*.tmp
.env
```

- [ ] **Step 3: Write `config.yaml`** (brand IDs looked up on 2026-09-27 via vinted.ro `/api/v2/brands?keyword=`)

```yaml
# Vinted sell-time tracker settings.
# Spec: docs/superpowers/specs/2026-09-27-vinted-sell-time-tracker-design.md
base_url: https://www.vinted.ro
headless: true

# catalog 5 = Men. Brand IDs from vinted.ro /api/v2/brands (looked up 2026-09-27).
queries:
  - name: streetwear
    catalog_ids: [5]
    brand_ids:
      - 53       # Nike
      - 5977     # Nike Air
      - 14       # adidas
      - 194976   # adidas Originals
      - 2319     # The North Face
      - 362      # Carhartt
      - 872289   # Carhartt WIP
      - 441      # Stüssy
  - name: premium_casual
    catalog_ids: [5]
    brand_ids:
      - 88       # Ralph Lauren
      - 4273     # Polo Ralph Lauren
      - 94       # Tommy Hilfiger
      - 304      # Lacoste
      - 120      # Hugo Boss
      - 6039857  # BOSS Hugo Boss
      - 1707868  # HUGO Hugo Boss
  - name: designer   # no price filter on purpose: cheap and possibly fake listings are tracked too
    catalog_ids: [5]
    brand_ids:
      - 73306    # Stone Island
      - 73952    # C.P. Company
      - 6539     # Moncler

discovery:
  poll_minutes: 5
  max_item_age_minutes: 60
  max_new_per_day: 250
  whole_price_prefilter: true   # skip catalog prices with decimals (currency-converted = foreign seller); validated in Task 8

recheck:
  schedule:          # [item age below N hours, check every M hours]
    - [24, 2]
    - [168, 8]
    - [720, 24]      # the last row's age is where tracking stops (30 days)
  uncertain_gap_hours: 48

rate:
  min_delay_s: 8
  max_delay_s: 12
  max_pages_per_hour: 360

backoff_minutes: [30, 60, 120, 240]
```

- [ ] **Step 4: Write `spike/watch.py`**

```python
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
```

- [ ] **Step 5: Write `spike/make_fixture.py`**

```python
"""THROWAWAY helper: turn one spike snapshot into a test fixture.

Usage: .venv\\Scripts\\python spike\\make_fixture.py spike/out/<snapshot-base> <fixture-name>
(<snapshot-base> is the file name without .html, e.g. spike/out/10151209174-20260928T101500)
"""
import gzip
import shutil
import sys
from pathlib import Path

src, name = sys.argv[1], sys.argv[2]
dst = Path("tests/fixtures")
dst.mkdir(parents=True, exist_ok=True)
(dst / f"{name}.html.gz").write_bytes(gzip.compress(Path(f"{src}.html").read_bytes()))
shutil.copyfile(f"{src}.txt", dst / f"{name}.txt")
shutil.copyfile(f"{src}.meta.json", dst / f"{name}.meta.json")
print("wrote fixture", name)
```

- [ ] **Step 6: Write `spike/prefilter_check.py`** (run in Task 8, after the parser exists)

```python
"""THROWAWAY: is 'catalog price has decimals => foreign seller' safe?"""
import json
from pathlib import Path

from vinted_tracker.parse import parse_catalog

catalog = {i.id: i for i in parse_catalog(Path("spike/out/catalog.html").read_text(encoding="utf-8"))}
first: dict[int, dict] = {}
for line in Path("spike/out/changes.jsonl").read_text(encoding="utf-8").splitlines():
    row = json.loads(line)
    first.setdefault(row["id"], row)


def has_decimals(item_id: int) -> bool:
    price = catalog[item_id].price_ron
    return price is not None and price != price.to_integral_value()


ron = [i for i, r in first.items() if r.get("currency") == "RON" and i in catalog]
foreign = [i for i, r in first.items() if r.get("currency") not in (None, "RON") and i in catalog]
print(f"items={len(first)} RON={len(ron)} foreign={len(foreign)}")
print(f"RON sellers WITH decimals (would be wrongly skipped): {sum(has_decimals(i) for i in ron)}")
print(f"foreign sellers WITHOUT decimals (would still cost a page visit): {sum(not has_decimals(i) for i in foreign)}")
```

- [ ] **Step 7: Start the spike in the background** against the whole watchlist (all 18 brand IDs):

```powershell
.venv\Scripts\python spike\watch.py "https://www.vinted.ro/catalog?catalog[]=5&brand_ids[]=53&brand_ids[]=5977&brand_ids[]=14&brand_ids[]=194976&brand_ids[]=2319&brand_ids[]=362&brand_ids[]=872289&brand_ids[]=441&brand_ids[]=88&brand_ids[]=4273&brand_ids[]=94&brand_ids[]=304&brand_ids[]=120&brand_ids[]=6039857&brand_ids[]=1707868&brand_ids[]=73306&brand_ids[]=73952&brand_ids[]=6539&order=newest_first" 50 24 > spike\watch.log
```
Run it with the Bash/PowerShell tool's `run_in_background: true`.
Expected within 2 minutes: `spike\watch.log` shows `watching 50 items for 24.0 h`, then one line per item. If it prints `Blocked on the catalog page`, re-run with `--headed` and note in the findings that headless mode is blocked (then set `headless: false` in `config.yaml`).

- [ ] **Step 8: Commit**

```powershell
git add .gitignore config.yaml spike/watch.py spike/make_fixture.py spike/prefilter_check.py
git commit -m "Add Phase 0 spike scripts and watchlist config"
```

- [ ] **Step 9: Controller: update progress page.** Phase 0 → `active`, note "Spike running since <time>; harvest after 24 h".

---

### Task 2: Package skeleton, models, config loader, test helpers

**Files:**
- Create: `pyproject.toml`, `.env.example`, `vinted_tracker/__init__.py`, `vinted_tracker/models.py`, `vinted_tracker/config.py`, `tests/conftest.py`, `tests/helpers.py`, `tests/test_config.py`

**Interfaces:**
- Produces:
  - `models.Status` (StrEnum: `AVAILABLE, RESERVED, SOLD, HIDDEN, DELETED, UNKNOWN`), `models.UNSOLD_FINAL = "unsold_30d"`, `models.utcnow() -> datetime`
  - `models.FetchedPage(url: str, status: int, html: str, text: str)`
  - `models.CatalogItem(id: int, title: str, url: str, price_ron: Decimal|None, favourite_count: int|None, seller_id: int|None, brand: str|None, size: str|None, condition: str|None, raw: dict)`
  - `models.ItemSnapshot(item_id: int, status: Status, price: Decimal|None, currency: str|None, favourite_count: int|None, catalog_id: int|None, upload_age: timedelta|None, raw: dict)`
  - `config.Query(name, catalog_ids: tuple[int,...], brand_ids: tuple[int,...], price_from: float|None, price_to: float|None)`
  - `config.Config(base_url, queries, poll_minutes, max_item_age_minutes, max_new_per_day, whole_price_prefilter, recheck_schedule: tuple[tuple[float,float],...], uncertain_gap_hours, min_delay_s, max_delay_s, max_pages_per_hour, backoff_minutes: tuple[float,...], headless, database_url)`
  - `config.load_config(path, env=None) -> Config`, `config.ConfigError`
  - `tests/helpers.py`: `make_html`, `rsc_row`, `catalog_entry`, `catalog_html`, `catalog_page`, `item_page`, `load_fixture`, `load_expected`, `make_config`, `make_catalog_item`, `make_snapshot`, `FakeFetcher`, `BlockingFetcher`, `BASE`
  - `tests/conftest.py`: fixture `conn` (clean test database, skips if `TEST_DATABASE_URL` is missing)

- [ ] **Step 1: Write `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "vinted-tracker"
version = "0.1.0"
description = "Tracks how long new men's listings on vinted.ro take to sell"
requires-python = ">=3.12"
dependencies = [
    "playwright>=1.47",
    "psycopg[binary]>=3.2",
    "PyYAML>=6.0",
    "python-dotenv>=1.0",
    "pandas>=2.2",
    "openpyxl>=3.1",
]

[project.optional-dependencies]
dev = ["pytest>=8"]

[tool.setuptools]
packages = ["vinted_tracker"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 2: Write `.env.example`** and ask the user to create `.env`

```
# Copy to .env and replace CHANGE_ME with the password you gave the `vinted` role.
DATABASE_URL=postgresql://vinted:CHANGE_ME@localhost:5432/vinted_tracker
TEST_DATABASE_URL=postgresql://vinted:CHANGE_ME@localhost:5432/vinted_tracker_test
# Only for docker-compose on the VPS later:
POSTGRES_PASSWORD=CHANGE_ME
```
Then tell the user: "Copy `.env.example` to `.env` and put your `vinted` password in place of `CHANGE_ME` (`Copy-Item .env.example .env`, then edit)." Do not ask for the password.

- [ ] **Step 3: Install the package in editable mode**

```powershell
.venv\Scripts\python -m pip install -e ".[dev]"
```
Expected: `Successfully installed ... vinted-tracker-0.1.0`.

- [ ] **Step 4: Write `vinted_tracker/__init__.py` and `vinted_tracker/models.py`**

`vinted_tracker/__init__.py`:
```python
"""Vinted sell-time tracker."""

__version__ = "0.1.0"
```

`vinted_tracker/models.py`:
```python
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
```

- [ ] **Step 5: Write the failing config tests** in `tests/test_config.py`

```python
import textwrap
from pathlib import Path

import pytest

from vinted_tracker.config import ConfigError, load_config

VALID = textwrap.dedent(
    """
    base_url: https://www.vinted.ro/
    headless: true
    queries:
      - name: streetwear
        catalog_ids: [5]
        brand_ids: [53, 14]
      - name: designer
        catalog_ids: [5]
        brand_ids: [73306]
        price_from: null
        price_to: null
    discovery:
      poll_minutes: 5
      max_item_age_minutes: 60
      max_new_per_day: 250
      whole_price_prefilter: true
    recheck:
      schedule: [[24, 2], [168, 8], [720, 24]]
      uncertain_gap_hours: 48
    rate:
      min_delay_s: 8
      max_delay_s: 12
      max_pages_per_hour: 360
    backoff_minutes: [30, 60, 120, 240]
    """
)
ENV = {"DATABASE_URL": "postgresql://u:p@localhost/db"}


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_valid_config(tmp_path):
    cfg = load_config(write(tmp_path, VALID), ENV)
    assert cfg.base_url == "https://www.vinted.ro"
    assert [q.name for q in cfg.queries] == ["streetwear", "designer"]
    assert cfg.queries[0].brand_ids == (53, 14)
    assert cfg.queries[1].price_from is None
    assert cfg.recheck_schedule == ((24.0, 2.0), (168.0, 8.0), (720.0, 24.0))
    assert cfg.whole_price_prefilter is True
    assert cfg.backoff_minutes == (30.0, 60.0, 120.0, 240.0)
    assert cfg.database_url == ENV["DATABASE_URL"]


def test_missing_database_url(tmp_path):
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        load_config(write(tmp_path, VALID), {})


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml", ENV)


def test_query_needs_ids(tmp_path):
    bad = VALID.replace("    catalog_ids: [5]\n    brand_ids: [53, 14]", "    catalog_ids: []")
    with pytest.raises(ConfigError, match="catalog_ids or brand_ids"):
        load_config(write(tmp_path, bad), ENV)


def test_schedule_must_ascend(tmp_path):
    bad = VALID.replace("[[24, 2], [168, 8], [720, 24]]", "[[168, 8], [24, 2]]")
    with pytest.raises(ConfigError, match="schedule"):
        load_config(write(tmp_path, bad), ENV)


def test_min_delay_not_above_max(tmp_path):
    bad = VALID.replace("min_delay_s: 8", "min_delay_s: 20")
    with pytest.raises(ConfigError, match="min_delay_s"):
        load_config(write(tmp_path, bad), ENV)


def test_duplicate_query_names(tmp_path):
    bad = VALID.replace("name: designer", "name: streetwear")
    with pytest.raises(ConfigError, match="unique"):
        load_config(write(tmp_path, bad), ENV)


def test_project_config_is_valid():
    cfg = load_config(Path(__file__).resolve().parents[1] / "config.yaml", ENV)
    assert {q.name for q in cfg.queries} == {"streetwear", "premium_casual", "designer"}
    assert all(q.brand_ids for q in cfg.queries)
```

- [ ] **Step 6: Run to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vinted_tracker.config'`.

- [ ] **Step 7: Write `vinted_tracker/config.py`**

```python
"""Load and validate config.yaml plus DATABASE_URL from the environment."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


class ConfigError(ValueError):
    """The configuration is missing or invalid."""


@dataclass(frozen=True)
class Query:
    name: str
    catalog_ids: tuple[int, ...]
    brand_ids: tuple[int, ...]
    price_from: float | None = None
    price_to: float | None = None


@dataclass(frozen=True)
class Config:
    base_url: str
    queries: tuple[Query, ...]
    poll_minutes: float
    max_item_age_minutes: float
    max_new_per_day: int
    whole_price_prefilter: bool
    recheck_schedule: tuple[tuple[float, float], ...]  # (max_age_hours, interval_hours), ascending
    uncertain_gap_hours: float
    min_delay_s: float
    max_delay_s: float
    max_pages_per_hour: int
    backoff_minutes: tuple[float, ...]
    headless: bool
    database_url: str


def load_config(path: str | Path, env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path}") from exc
    database_url = env.get("DATABASE_URL", "")
    if not database_url:
        raise ConfigError("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
    try:
        discovery, recheck, rate = data["discovery"], data["recheck"], data["rate"]
        cfg = Config(
            base_url=str(data.get("base_url", "https://www.vinted.ro")).rstrip("/"),
            queries=tuple(_query(q) for q in data["queries"]),
            poll_minutes=float(discovery["poll_minutes"]),
            max_item_age_minutes=float(discovery["max_item_age_minutes"]),
            max_new_per_day=int(discovery["max_new_per_day"]),
            whole_price_prefilter=bool(discovery.get("whole_price_prefilter", True)),
            recheck_schedule=tuple((float(age), float(every)) for age, every in recheck["schedule"]),
            uncertain_gap_hours=float(recheck["uncertain_gap_hours"]),
            min_delay_s=float(rate["min_delay_s"]),
            max_delay_s=float(rate["max_delay_s"]),
            max_pages_per_hour=int(rate["max_pages_per_hour"]),
            backoff_minutes=tuple(float(m) for m in data["backoff_minutes"]),
            headless=bool(data.get("headless", True)),
            database_url=database_url,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid config {path}: {exc!r}") from exc
    _validate(cfg)
    return cfg


def _query(raw: dict[str, Any]) -> Query:
    return Query(
        name=str(raw["name"]),
        catalog_ids=tuple(int(x) for x in raw.get("catalog_ids") or ()),
        brand_ids=tuple(int(x) for x in raw.get("brand_ids") or ()),
        price_from=_optional_float(raw.get("price_from")),
        price_to=_optional_float(raw.get("price_to")),
    )


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _validate(cfg: Config) -> None:
    if not cfg.queries:
        raise ConfigError("At least one query is required.")
    names = [q.name for q in cfg.queries]
    if len(set(names)) != len(names):
        raise ConfigError("Query names must be unique.")
    for q in cfg.queries:
        if not q.catalog_ids and not q.brand_ids:
            raise ConfigError(f"Query {q.name!r} needs catalog_ids or brand_ids.")
        if q.price_from is not None and q.price_to is not None and q.price_from > q.price_to:
            raise ConfigError(f"Query {q.name!r}: price_from is above price_to.")
    if not 0 < cfg.min_delay_s <= cfg.max_delay_s:
        raise ConfigError("rate: need 0 < min_delay_s <= max_delay_s.")
    if cfg.max_pages_per_hour <= 0:
        raise ConfigError("rate: max_pages_per_hour must be positive.")
    ages = [age for age, _ in cfg.recheck_schedule]
    if not ages or ages != sorted(ages) or any(every <= 0 for _, every in cfg.recheck_schedule):
        raise ConfigError("recheck.schedule must be non-empty, ascending by age, with positive intervals.")
    if not cfg.backoff_minutes or any(m <= 0 for m in cfg.backoff_minutes):
        raise ConfigError("backoff_minutes must be a non-empty list of positive numbers.")
```

- [ ] **Step 8: Write `tests/conftest.py` and `tests/helpers.py`**

`tests/conftest.py`:
```python
import os
from pathlib import Path

import pytest
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def _test_database_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL") or dotenv_values(ROOT / ".env").get("TEST_DATABASE_URL")


@pytest.fixture
def conn():
    from vinted_tracker import db

    url = _test_database_url()
    if not url:
        pytest.skip("TEST_DATABASE_URL not set (see .env.example)")
    connection = db.connect(url)
    db.init_schema(connection)
    connection.execute("TRUNCATE items, observations, skipped_items, query_state, runs RESTART IDENTITY CASCADE")
    yield connection
    connection.close()
```

`tests/helpers.py`:
```python
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
```

- [ ] **Step 9: Run the config tests**

Run: `.venv\Scripts\python -m pytest tests/test_config.py -v`
Expected: 8 passed.

- [ ] **Step 10: Commit**

```powershell
git add pyproject.toml .env.example vinted_tracker tests
git commit -m "Add package skeleton, models, config loader and test helpers"
```

- [ ] **Step 11: Controller: update progress page.** Phase 1 → `active`, note "Skeleton + config done".

---

### Task 3: Database layer

**Files:**
- Create: `vinted_tracker/db.py`, `tests/test_db.py`

**Interfaces:**
- Consumes: `models.CatalogItem`, `models.ItemSnapshot`, `models.Status`; test helpers `make_catalog_item`, `make_snapshot`, fixture `conn`.
- Produces (all take `conn` first):
  - `connect(url) -> psycopg.Connection` (autocommit, dict rows); `init_schema(conn)`
  - `is_known(conn, item_id) -> bool`
  - `insert_item(conn, *, item, snap, query_name, uploaded_at, first_seen_at, next_check_at) -> bool`
  - `add_skipped(conn, item_id, reason, seen_at)`
  - `get_query_state(conn, name) -> tuple[int, datetime] | None`; `set_query_state(conn, name, high_water_id, polled_at)`
  - `count_new_since(conn, since) -> int`
  - `due_items(conn, now, limit) -> list[dict]` (keys `id, url, uploaded_at, next_check_at`); `count_due(conn, now) -> int`; `next_due_at(conn) -> datetime | None`
  - `add_observation(conn, item_id, observed_at, status, price_ron, favourite_count, raw)`; `last_observation(conn, item_id) -> dict | None`; `observations_for(conn, item_id) -> list[tuple[datetime, Status]]`
  - `update_item_after_check(conn, item_id, *, checked_at, next_check_at, final_status, sold_after_min, sold_after_max, uncertain)`
  - `status_counts(conn) -> dict[str, int]` (`"tracking"` for items without a final status)
  - `start_run(conn, started_at) -> int`; `finish_run(conn, run_id, ended_at, *, pages_loaded, items_discovered, items_rechecked, blocks, parse_errors)`

- [ ] **Step 1: Check the test database is reachable**

```powershell
.venv\Scripts\python -c "import psycopg; from dotenv import dotenv_values; psycopg.connect(dotenv_values('.env')['TEST_DATABASE_URL']).close(); print('test DB OK')"
```
Expected: `test DB OK`. If it fails, ask the user to check `.env` (the password or the database names from the setup).

- [ ] **Step 2: Write the failing tests** in `tests/test_db.py`

```python
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from helpers import make_catalog_item, make_snapshot

from vinted_tracker import db
from vinted_tracker.models import Status

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def track(conn, item_id=1001, uploaded=T0, next_check=None):
    return db.insert_item(
        conn,
        item=make_catalog_item(item_id),
        snap=make_snapshot(item_id),
        query_name="streetwear",
        uploaded_at=uploaded,
        first_seen_at=uploaded + timedelta(minutes=5),
        next_check_at=next_check or uploaded + timedelta(hours=2),
    )


def test_insert_item_stores_item_and_first_observation(conn):
    assert track(conn) is True
    row = conn.execute("SELECT * FROM items WHERE id = 1001").fetchone()
    assert row["brand"] == "Nike"
    assert row["price_listed_ron"] == Decimal("80.00")
    assert row["catalog_id"] == 1803
    assert row["raw_first"]["item"]["buy"]["can_buy"] is True
    assert db.observations_for(conn, 1001) == [(T0 + timedelta(minutes=5), Status.AVAILABLE)]
    assert db.last_observation(conn, 1001)["raw"] == {"buy": {"can_buy": True}}


def test_insert_is_idempotent(conn):
    assert track(conn) is True
    assert track(conn) is False
    assert conn.execute("SELECT count(*) AS n FROM items").fetchone()["n"] == 1
    assert conn.execute("SELECT count(*) AS n FROM observations").fetchone()["n"] == 1


def test_is_known_covers_items_and_skipped(conn):
    assert not db.is_known(conn, 1001)
    track(conn)
    assert db.is_known(conn, 1001)
    db.add_skipped(conn, 2002, "foreign_seller", T0)
    db.add_skipped(conn, 2002, "foreign_seller", T0)  # idempotent
    assert db.is_known(conn, 2002)


def test_query_state_roundtrip(conn):
    assert db.get_query_state(conn, "streetwear") is None
    db.set_query_state(conn, "streetwear", 100, T0)
    assert db.get_query_state(conn, "streetwear") == (100, T0)
    db.set_query_state(conn, "streetwear", 150, T0 + timedelta(minutes=5))
    assert db.get_query_state(conn, "streetwear") == (150, T0 + timedelta(minutes=5))


def test_due_items_oldest_first_and_excludes_final(conn):
    track(conn, 1, next_check=T0 + timedelta(hours=3))
    track(conn, 2, next_check=T0 + timedelta(hours=1))
    track(conn, 3, next_check=T0 + timedelta(hours=2))
    db.update_item_after_check(
        conn, 3, checked_at=T0, next_check_at=None, final_status="sold",
        sold_after_min=timedelta(hours=1), sold_after_max=timedelta(hours=2), uncertain=False,
    )
    later = T0 + timedelta(days=1)
    assert [r["id"] for r in db.due_items(conn, later, limit=10)] == [2, 1]
    assert db.count_due(conn, later) == 2
    assert db.count_due(conn, T0 + timedelta(minutes=90)) == 1
    assert db.next_due_at(conn) == T0 + timedelta(hours=1)


def test_count_new_since(conn):
    track(conn, 1)  # first seen at T0 + 5 min
    assert db.count_new_since(conn, T0) == 1
    assert db.count_new_since(conn, T0 + timedelta(hours=1)) == 0


def test_observations_and_status_counts(conn):
    track(conn, 1)
    track(conn, 2)
    db.add_observation(conn, 1, T0 + timedelta(hours=2), Status.SOLD, Decimal("75"), 3, {"buy": {"can_buy": False}})
    assert db.last_observation(conn, 1)["status"] == "sold"
    db.update_item_after_check(
        conn, 1, checked_at=T0 + timedelta(hours=2), next_check_at=None, final_status="sold",
        sold_after_min=timedelta(minutes=5), sold_after_max=timedelta(hours=2), uncertain=False,
    )
    row = conn.execute("SELECT * FROM items WHERE id = 1").fetchone()
    assert row["sold_after_max"] == timedelta(hours=2)
    assert db.status_counts(conn) == {"tracking": 1, "sold": 1}


def test_runs(conn):
    run_id = db.start_run(conn, T0)
    db.finish_run(conn, run_id, T0 + timedelta(hours=1), pages_loaded=5, items_discovered=2,
                  items_rechecked=3, blocks=0, parse_errors=1)
    row = conn.execute("SELECT * FROM runs WHERE id = %s", (run_id,)).fetchone()
    assert (row["pages_loaded"], row["items_discovered"], row["parse_errors"]) == (5, 2, 1)
    assert row["ended_at"] == T0 + timedelta(hours=1)
```

- [ ] **Step 3: Run to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_db.py -v`
Expected: FAIL with `ImportError: cannot import name 'db'`.

- [ ] **Step 4: Write `vinted_tracker/db.py`**

```python
"""PostgreSQL storage: tracked items, observations, skipped items, query state, runs."""
from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .models import CatalogItem, ItemSnapshot, Status

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id               bigint PRIMARY KEY,
    title            text NOT NULL,
    url              text NOT NULL,
    brand            text,
    catalog_id       integer,
    size             text,
    condition        text,
    price_listed_ron numeric(12, 2),
    seller_id        bigint,
    query_name       text NOT NULL,
    uploaded_at      timestamptz NOT NULL,
    first_seen_at    timestamptz NOT NULL,
    final_status     text,
    sold_after_min   interval,
    sold_after_max   interval,
    uncertain        boolean NOT NULL DEFAULT false,
    last_checked_at  timestamptz,
    next_check_at    timestamptz,
    raw_first        jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS items_due_idx ON items (next_check_at) WHERE final_status IS NULL;

CREATE TABLE IF NOT EXISTS observations (
    id              bigserial PRIMARY KEY,
    item_id         bigint NOT NULL REFERENCES items (id) ON DELETE CASCADE,
    observed_at     timestamptz NOT NULL,
    status          text NOT NULL,
    price_ron       numeric(12, 2),
    favourite_count integer,
    raw             jsonb
);
CREATE INDEX IF NOT EXISTS observations_item_idx ON observations (item_id, observed_at);

CREATE TABLE IF NOT EXISTS skipped_items (
    id      bigint PRIMARY KEY,
    reason  text NOT NULL,
    seen_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS query_state (
    name           text PRIMARY KEY,
    high_water_id  bigint NOT NULL,
    last_polled_at timestamptz NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id               bigserial PRIMARY KEY,
    started_at       timestamptz NOT NULL,
    ended_at         timestamptz,
    pages_loaded     integer NOT NULL DEFAULT 0,
    items_discovered integer NOT NULL DEFAULT 0,
    items_rechecked  integer NOT NULL DEFAULT 0,
    blocks           integer NOT NULL DEFAULT 0,
    parse_errors     integer NOT NULL DEFAULT 0
);
"""


def connect(url: str) -> psycopg.Connection:
    return psycopg.connect(url, autocommit=True, row_factory=dict_row)


def init_schema(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA)


def is_known(conn: psycopg.Connection, item_id: int) -> bool:
    row = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM items WHERE id = %(id)s)"
        " OR EXISTS (SELECT 1 FROM skipped_items WHERE id = %(id)s) AS known",
        {"id": item_id},
    ).fetchone()
    return bool(row["known"])


def insert_item(
    conn: psycopg.Connection,
    *,
    item: CatalogItem,
    snap: ItemSnapshot,
    query_name: str,
    uploaded_at: datetime,
    first_seen_at: datetime,
    next_check_at: datetime | None,
) -> bool:
    """Start tracking an item and store its first observation. Returns False if it was already tracked."""
    price = snap.price if snap.currency == "RON" and snap.price is not None else item.price_ron
    favourites = snap.favourite_count if snap.favourite_count is not None else item.favourite_count
    with conn.transaction():
        cur = conn.execute(
            """
            INSERT INTO items (id, title, url, brand, catalog_id, size, condition, price_listed_ron,
                               seller_id, query_name, uploaded_at, first_seen_at, last_checked_at,
                               next_check_at, raw_first)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (
                item.id, item.title, item.url, item.brand, snap.catalog_id, item.size, item.condition,
                price, item.seller_id, query_name, uploaded_at, first_seen_at, first_seen_at,
                next_check_at, Jsonb({"catalog": item.raw, "item": snap.raw}),
            ),
        )
        if cur.rowcount == 0:
            return False
        conn.execute(
            "INSERT INTO observations (item_id, observed_at, status, price_ron, favourite_count, raw)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (item.id, first_seen_at, snap.status.value, price, favourites, Jsonb(snap.raw)),
        )
    return True


def add_skipped(conn: psycopg.Connection, item_id: int, reason: str, seen_at: datetime) -> None:
    conn.execute(
        "INSERT INTO skipped_items (id, reason, seen_at) VALUES (%s, %s, %s) ON CONFLICT (id) DO NOTHING",
        (item_id, reason, seen_at),
    )


def get_query_state(conn: psycopg.Connection, name: str) -> tuple[int, datetime] | None:
    row = conn.execute(
        "SELECT high_water_id, last_polled_at FROM query_state WHERE name = %s", (name,)
    ).fetchone()
    return None if row is None else (row["high_water_id"], row["last_polled_at"])


def set_query_state(conn: psycopg.Connection, name: str, high_water_id: int, polled_at: datetime) -> None:
    conn.execute(
        """
        INSERT INTO query_state (name, high_water_id, last_polled_at) VALUES (%s, %s, %s)
        ON CONFLICT (name) DO UPDATE
            SET high_water_id = EXCLUDED.high_water_id, last_polled_at = EXCLUDED.last_polled_at
        """,
        (name, high_water_id, polled_at),
    )


def count_new_since(conn: psycopg.Connection, since: datetime) -> int:
    return conn.execute("SELECT count(*) AS n FROM items WHERE first_seen_at >= %s", (since,)).fetchone()["n"]


def due_items(conn: psycopg.Connection, now: datetime, limit: int) -> list[dict]:
    return conn.execute(
        """
        SELECT id, url, uploaded_at, next_check_at FROM items
        WHERE final_status IS NULL AND next_check_at <= %s
        ORDER BY next_check_at, id
        LIMIT %s
        """,
        (now, limit),
    ).fetchall()


def count_due(conn: psycopg.Connection, now: datetime) -> int:
    return conn.execute(
        "SELECT count(*) AS n FROM items WHERE final_status IS NULL AND next_check_at <= %s", (now,)
    ).fetchone()["n"]


def next_due_at(conn: psycopg.Connection) -> datetime | None:
    return conn.execute(
        "SELECT min(next_check_at) AS t FROM items WHERE final_status IS NULL"
    ).fetchone()["t"]


def add_observation(
    conn: psycopg.Connection,
    item_id: int,
    observed_at: datetime,
    status: Status,
    price_ron: Decimal | None,
    favourite_count: int | None,
    raw: dict | None,
) -> None:
    conn.execute(
        "INSERT INTO observations (item_id, observed_at, status, price_ron, favourite_count, raw)"
        " VALUES (%s, %s, %s, %s, %s, %s)",
        (item_id, observed_at, status.value, price_ron, favourite_count, None if raw is None else Jsonb(raw)),
    )


def last_observation(conn: psycopg.Connection, item_id: int) -> dict | None:
    return conn.execute(
        "SELECT * FROM observations WHERE item_id = %s ORDER BY observed_at DESC, id DESC LIMIT 1",
        (item_id,),
    ).fetchone()


def observations_for(conn: psycopg.Connection, item_id: int) -> list[tuple[datetime, Status]]:
    rows = conn.execute(
        "SELECT observed_at, status FROM observations WHERE item_id = %s ORDER BY observed_at, id",
        (item_id,),
    ).fetchall()
    return [(r["observed_at"], Status(r["status"])) for r in rows]


def update_item_after_check(
    conn: psycopg.Connection,
    item_id: int,
    *,
    checked_at: datetime,
    next_check_at: datetime | None,
    final_status: str | None,
    sold_after_min: timedelta | None,
    sold_after_max: timedelta | None,
    uncertain: bool,
) -> None:
    conn.execute(
        """
        UPDATE items
        SET last_checked_at = %s, next_check_at = %s, final_status = %s,
            sold_after_min = %s, sold_after_max = %s, uncertain = %s
        WHERE id = %s
        """,
        (checked_at, next_check_at, final_status, sold_after_min, sold_after_max, uncertain, item_id),
    )


def status_counts(conn: psycopg.Connection) -> dict[str, int]:
    rows = conn.execute(
        "SELECT coalesce(final_status, 'tracking') AS status, count(*) AS n FROM items GROUP BY 1"
    ).fetchall()
    return {r["status"]: r["n"] for r in rows}


def start_run(conn: psycopg.Connection, started_at: datetime) -> int:
    return conn.execute("INSERT INTO runs (started_at) VALUES (%s) RETURNING id", (started_at,)).fetchone()["id"]


def finish_run(
    conn: psycopg.Connection,
    run_id: int,
    ended_at: datetime,
    *,
    pages_loaded: int,
    items_discovered: int,
    items_rechecked: int,
    blocks: int,
    parse_errors: int,
) -> None:
    conn.execute(
        """
        UPDATE runs SET ended_at = %s, pages_loaded = %s, items_discovered = %s,
                        items_rechecked = %s, blocks = %s, parse_errors = %s
        WHERE id = %s
        """,
        (ended_at, pages_loaded, items_discovered, items_rechecked, blocks, parse_errors, run_id),
    )
```

- [ ] **Step 5: Run the tests**

Run: `.venv\Scripts\python -m pytest tests/test_db.py -v`
Expected: 8 passed.

- [ ] **Step 6: Commit**

```powershell
git add vinted_tracker/db.py tests/test_db.py
git commit -m "Add PostgreSQL storage layer"
```

- [ ] **Step 7: Controller: update progress page.** Phase 1 → `done`.

---

### Task 4: Page payload decoding + catalog parser

**Files:**
- Create: `vinted_tracker/parse.py`, `tests/test_parse_catalog.py`

**Interfaces:**
- Consumes: `models.CatalogItem`; helpers `make_html`, `rsc_row`, `catalog_entry`, `catalog_html`.
- Produces: `parse.ParseError`, `parse.rsc_text(html) -> str`, `parse.iter_json_values(rsc) -> Iterator[Any]`, `parse.iter_dicts(node) -> Iterator[dict]`, `parse.all_dicts(html) -> list[dict]`, `parse.parse_catalog(html) -> list[CatalogItem]`. Private helpers `_money`, `_int` are reused by Task 5.

Page facts (probe 2026-09-27): catalog entries live in a dict `{"items": {"items": [entry, ...]}}`. Each entry is `{"id", "productItem": {"id","title","url","favouriteCount","price":{"amount","currencyCode"},"user":{"id",...},"itemBox":{"accessibilityLabel": "<title>, Brand: X, Stare: Y, Mărime: Z, 91.51 lei, 99.59 lei"}, ...}, "catalogTracking"}`.

- [ ] **Step 1: Write the failing tests** in `tests/test_parse_catalog.py`

```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_parse_catalog.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vinted_tracker.parse'`.

- [ ] **Step 3: Write `vinted_tracker/parse.py`** (catalog part. Task 5 appends the item part.)

```python
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
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python -m pytest tests/test_parse_catalog.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```powershell
git add vinted_tracker/parse.py tests/test_parse_catalog.py
git commit -m "Add Next.js payload decoding and catalog parser"
```

- [ ] **Step 6: Controller: update progress page.** Phase 2 → `active`.

---

### Task 5: Item page parser + upload age

**Files:**
- Modify: `vinted_tracker/parse.py` (append)
- Create: `tests/test_parse_item.py`, `tests/test_parse_fixtures.py`

**Interfaces:**
- Consumes: `models.FetchedPage`, `models.ItemSnapshot`, `models.Status`; `parse.all_dicts`, `_money`, `_int` from Task 4; helpers `item_page`, `make_html`, `rsc_row`, `load_fixture`, `load_expected`.
- Produces: `parse.parse_item(page: FetchedPage, item_id: int) -> ItemSnapshot`, `parse.parse_upload_age(text: str) -> timedelta | None`.

Page facts (probe 2026-09-27): the item page holds `{"can_buy", "instant_buy", "is_hidden", "is_reserved", "item_id": "<id>", ...}` and a `make_offer` object `{"price": {"amount": "150", "currency_code": "PLN"}, "seller_id", "title"}` holding the **seller's original currency**, plus `catalog_id` and `favourite_count`. The visible text holds "Încărcat acum 3 minute". The sold / reserved / deleted appearance is **assumed** below and confirmed in Task 8.

- [ ] **Step 1: Write the failing tests** in `tests/test_parse_item.py`

```python
from datetime import timedelta
from decimal import Decimal

import pytest
from helpers import BASE, item_page, make_html, rsc_row

from vinted_tracker.models import FetchedPage, Status
from vinted_tracker.parse import ParseError, parse_item, parse_upload_age


def test_available_romanian_item():
    snap = parse_item(item_page(555), 555)
    assert snap.status is Status.AVAILABLE
    assert snap.price == Decimal("120.0")
    assert snap.currency == "RON"
    assert snap.favourite_count == 4
    assert snap.catalog_id == 1803
    assert snap.upload_age == timedelta(minutes=3)
    assert snap.raw["buy"]["can_buy"] is True


def test_foreign_seller_currency():
    assert parse_item(item_page(555, currency="PLN", amount="150"), 555).currency == "PLN"


def test_reserved():
    assert parse_item(item_page(555, can_buy=False, is_reserved=True), 555).status is Status.RESERVED


def test_sold():
    page = item_page(555, can_buy=False, text="Vândut\nÎncărcat acum 2 zile")
    assert parse_item(page, 555).status is Status.SOLD


def test_hidden():
    assert parse_item(item_page(555, can_buy=False, is_hidden=True), 555).status is Status.HIDDEN


def test_buyable_item_with_sold_word_elsewhere_stays_available():
    page = item_page(555, text="Încărcat acum 3 minute\nArticole similare\nVândut")
    assert parse_item(page, 555).status is Status.AVAILABLE


def test_not_buyable_without_any_signal_is_unknown():
    assert parse_item(item_page(555, can_buy=False), 555).status is Status.UNKNOWN


def test_http_404_is_deleted():
    page = FetchedPage(url=f"{BASE}/items/555", status=404, html="<html></html>", text="")
    snap = parse_item(page, 555)
    assert snap.status is Status.DELETED
    assert snap.raw == {"http_status": 404, "final_url": f"{BASE}/items/555"}


def test_redirect_away_from_item_is_deleted():
    page = FetchedPage(url=f"{BASE}/catalog", status=200, html="<html></html>", text="")
    assert parse_item(page, 555).status is Status.DELETED


def test_redirect_to_other_item_with_same_prefix_is_deleted():
    page = FetchedPage(url=f"{BASE}/items/5551-alt", status=200, html="<html></html>", text="")
    assert parse_item(page, 555).status is Status.DELETED


def test_missing_buy_state_raises():
    page = FetchedPage(url=f"{BASE}/items/555-x", status=200, html=make_html(rsc_row("1", {"x": 1})), text="")
    with pytest.raises(ParseError):
        parse_item(page, 555)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Încărcat acum 3 minute", timedelta(minutes=3)),
        ("Încărcat\nacum 3 minute", timedelta(minutes=3)),
        ("Încărcat acum 25 de minute", timedelta(minutes=25)),
        ("Încărcat acum un minut", timedelta(minutes=1)),
        ("Încărcat acum câteva secunde", timedelta(seconds=3)),
        ("Încărcat acum o oră", timedelta(hours=1)),
        ("Încărcat acum 2 ore", timedelta(hours=2)),
        ("Încărcat acum o zi", timedelta(days=1)),
        ("Încărcat acum 3 zile", timedelta(days=3)),
        ("Încărcat acum o săptămână", timedelta(days=7)),
        ("Încărcat acum 2 săptămâni", timedelta(days=14)),
        ("Încărcat acum o lună", timedelta(days=30)),
        ("Încărcat acum 2 luni", timedelta(days=60)),
        ("Încărcat acum un an", timedelta(days=365)),
        ("Nimic relevant aici", None),
    ],
)
def test_parse_upload_age(text, expected):
    assert parse_upload_age(text) == expected
```

`tests/test_parse_fixtures.py` (skips until Task 8 captures real pages):
```python
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
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_parse_item.py tests/test_parse_fixtures.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_item'`. (The fixture tests show as skipped once the import works.)

- [ ] **Step 3: Append the item parser to `vinted_tracker/parse.py`**

Add these imports at the top of `parse.py` (merge with the existing ones):
```python
import unicodedata
from datetime import timedelta

from .models import CatalogItem, FetchedPage, ItemSnapshot, Status
```

Append at the end of `parse.py`:
```python
_SOLD_RE = re.compile(r"\bVândut\b")
_UPLOAD_RE = re.compile(r"incarcat\s+(?:acum\s+)?([^\n]{1,40})")
_NUMBER_RE = re.compile(r"(\d+)\s+(?:de\s+)?(.*)")
_ARTICLE_RE = re.compile(r"(un|o|cateva)\s+(.*)")
_UNITS = (
    (re.compile(r"secund"), timedelta(seconds=1)),
    (re.compile(r"minut"), timedelta(minutes=1)),
    (re.compile(r"or[ae]\b"), timedelta(hours=1)),
    (re.compile(r"zi(le)?\b"), timedelta(days=1)),
    (re.compile(r"saptaman"), timedelta(days=7)),
    (re.compile(r"lun"), timedelta(days=30)),
    (re.compile(r"an(i)?\b"), timedelta(days=365)),
)


def parse_item(page: FetchedPage, item_id: int) -> ItemSnapshot:
    if page.status in (404, 410) or not re.search(rf"/items/{item_id}(?:[-/?#]|$)", page.url):
        return ItemSnapshot(
            item_id=item_id, status=Status.DELETED, price=None, currency=None, favourite_count=None,
            catalog_id=None, upload_age=None, raw={"http_status": page.status, "final_url": page.url},
        )
    dicts = all_dicts(page.html)
    buy = _first(dicts, lambda d: "can_buy" in d and str(d.get("item_id")) == str(item_id))
    if buy is None:
        buy = _first(dicts, lambda d: "can_buy" in d and "is_reserved" in d)
    if buy is None:
        raise ParseError(f"item {item_id}: no buy-state object in page data")
    offer = _first(
        dicts, lambda d: isinstance(d.get("price"), dict) and "currency_code" in d["price"] and "seller_id" in d
    )
    price, currency = _money(offer["price"]) if offer else (None, None)
    favourites = _first(dicts, lambda d: "favourite_count" in d)
    catalog = _first(dicts, lambda d: "catalog_id" in d)
    sold_text = bool(_SOLD_RE.search(page.text))
    return ItemSnapshot(
        item_id=item_id,
        status=_status(buy, sold_text),
        price=price,
        currency=currency,
        favourite_count=_int(favourites.get("favourite_count")) if favourites else None,
        catalog_id=_int(catalog.get("catalog_id")) if catalog else None,
        upload_age=parse_upload_age(page.text),
        raw={"buy": buy, "offer": offer, "sold_text": sold_text, "http_status": page.status},
    )


def _status(buy: dict, sold_text: bool) -> Status:
    if buy.get("can_buy") is True:
        return Status.AVAILABLE
    if buy.get("is_reserved") is True:
        return Status.RESERVED
    if sold_text:
        return Status.SOLD
    if buy.get("is_hidden") is True:
        return Status.HIDDEN
    return Status.UNKNOWN


def _first(dicts: list[dict], predicate) -> dict | None:
    return next((d for d in dicts if predicate(d)), None)


def _fold(text: str) -> str:
    """Lower-case and strip diacritics: 'Încărcat acum o oră' -> 'incarcat acum o ora'."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def parse_upload_age(text: str) -> timedelta | None:
    match = _UPLOAD_RE.search(_fold(text))
    if not match:
        return None
    phrase = match.group(1).strip()
    number = _NUMBER_RE.match(phrase)
    if number:
        count, rest = int(number.group(1)), number.group(2)
    else:
        article = _ARTICLE_RE.match(phrase)
        if not article:
            return None
        count = 3 if article.group(1) == "cateva" else 1
        rest = article.group(2)
    for pattern, unit in _UNITS:
        if pattern.match(rest):
            return unit * count
    return None
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python -m pytest tests/test_parse_item.py tests/test_parse_fixtures.py tests/test_parse_catalog.py -v`
Expected: 26 passed (11 + 15 parametrised), fixture tests skipped, catalog tests still pass.

- [ ] **Step 5: Commit**

```powershell
git add vinted_tracker/parse.py tests/test_parse_item.py tests/test_parse_fixtures.py
git commit -m "Add item page parser and upload-age parsing"
```

- [ ] **Step 6: Controller: update progress page.** Phase 2 note "Parsers done; waiting for real-page check (Task 8)".

---

### Task 6: Recheck schedule + outcome logic

**Files:**
- Create: `vinted_tracker/schedule.py`, `vinted_tracker/outcome.py`, `tests/test_schedule.py`, `tests/test_outcome.py`

**Interfaces:**
- Consumes: `models.Status`, `models.UNSOLD_FINAL`.
- Produces:
  - `schedule.stop_age(schedule) -> timedelta`
  - `schedule.check_interval(age: timedelta, schedule) -> timedelta | None`
  - `schedule.next_check_at(uploaded_at, now, schedule, stretch=1.0) -> datetime | None`
  - `schedule.stretch_factor(due_count: int, max_pages_per_hour: int, recheck_share=0.8) -> float`
  - `outcome.Outcome(final_status: str|None, sold_after_min: timedelta|None, sold_after_max: timedelta|None, uncertain: bool)`
  - `outcome.compute_outcome(uploaded_at, observations: list[tuple[datetime, Status]], now, *, stop_age: timedelta, uncertain_gap: timedelta) -> Outcome`

- [ ] **Step 1: Write the failing tests**

`tests/test_schedule.py`:
```python
from datetime import datetime, timedelta, timezone

from vinted_tracker.schedule import check_interval, next_check_at, stop_age, stretch_factor

SCHED = ((24.0, 2.0), (168.0, 8.0), (720.0, 24.0))
T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)


def test_stop_age():
    assert stop_age(SCHED) == timedelta(days=30)


def test_interval_bands():
    assert check_interval(timedelta(hours=1), SCHED) == timedelta(hours=2)
    assert check_interval(timedelta(hours=30), SCHED) == timedelta(hours=8)
    assert check_interval(timedelta(days=10), SCHED) == timedelta(hours=24)
    assert check_interval(timedelta(days=30), SCHED) is None


def test_next_check_normal():
    now = T0 + timedelta(minutes=10)
    assert next_check_at(T0, now, SCHED) == now + timedelta(hours=2)


def test_next_check_stretched():
    now = T0 + timedelta(minutes=10)
    assert next_check_at(T0, now, SCHED, stretch=1.5) == now + timedelta(hours=3)


def test_next_check_capped_at_stop():
    now = T0 + timedelta(days=29, hours=12)
    assert next_check_at(T0, now, SCHED) == T0 + timedelta(days=30)


def test_next_check_none_after_stop():
    assert next_check_at(T0, T0 + timedelta(days=30), SCHED) is None


def test_stretch_factor():
    assert stretch_factor(0, 360) == 1.0
    assert stretch_factor(288, 360) == 1.0
    assert stretch_factor(576, 360) == 2.0
```

`tests/test_outcome.py`:
```python
from datetime import datetime, timedelta, timezone

from vinted_tracker.models import Status
from vinted_tracker.outcome import Outcome, compute_outcome

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
A, R, S, H, D, U = Status.AVAILABLE, Status.RESERVED, Status.SOLD, Status.HIDDEN, Status.DELETED, Status.UNKNOWN
STOP = timedelta(days=30)
GAP = timedelta(hours=48)


def obs(*pairs):
    return [(T0 + timedelta(hours=h), s) for h, s in pairs]


def outcome(observations, now_hours):
    return compute_outcome(T0, observations, T0 + timedelta(hours=now_hours), stop_age=STOP, uncertain_gap=GAP)


def test_sold_between_last_available_and_first_sold():
    result = outcome(obs((0.1, A), (2, A), (4, S), (6, S)), 6)
    assert result == Outcome("sold", timedelta(hours=2), timedelta(hours=4), False)


def test_reserved_counts_as_live():
    assert outcome(obs((0.1, A), (2, R), (4, S)), 4).sold_after_min == timedelta(hours=2)


def test_unknown_observations_are_ignored():
    assert outcome(obs((0.1, A), (2, U), (4, S)), 4).sold_after_min == timedelta(hours=0.1)


def test_long_gap_is_uncertain():
    result = outcome(obs((0.1, A), (60, S)), 60)
    assert result.final_status == "sold"
    assert result.uncertain is True


def test_deleted_is_final_and_uncertain():
    assert outcome(obs((0.1, A), (5, D)), 5) == Outcome("deleted", None, None, True)


def test_still_tracking():
    assert outcome(obs((0.1, A), (2, A)), 3) == Outcome(None, None, None, False)


def test_hidden_is_not_final_before_stop():
    assert outcome(obs((0.1, A), (2, H)), 3).final_status is None


def test_unsold_after_stop():
    assert outcome(obs((0.1, A), (700, A)), 720).final_status == "unsold_30d"


def test_hidden_at_stop():
    assert outcome(obs((0.1, A), (700, H)), 720).final_status == "hidden"
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_schedule.py tests/test_outcome.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `vinted_tracker/schedule.py` and `vinted_tracker/outcome.py`**

`vinted_tracker/schedule.py`:
```python
"""When to check a tracked item next."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

Schedule = Sequence[tuple[float, float]]  # (max_age_hours, interval_hours), ascending


def stop_age(schedule: Schedule) -> timedelta:
    """Age at which tracking stops: the last row's max age."""
    return timedelta(hours=schedule[-1][0])


def check_interval(age: timedelta, schedule: Schedule) -> timedelta | None:
    hours = age.total_seconds() / 3600
    for max_age_hours, interval_hours in schedule:
        if hours < max_age_hours:
            return timedelta(hours=interval_hours)
    return None


def next_check_at(uploaded_at: datetime, now: datetime, schedule: Schedule, stretch: float = 1.0) -> datetime | None:
    """Next check time, never later than the stop age; None once the item has reached it."""
    interval = check_interval(now - uploaded_at, schedule)
    if interval is None:
        return None
    return min(now + interval * stretch, uploaded_at + stop_age(schedule))


def stretch_factor(due_count: int, max_pages_per_hour: int, recheck_share: float = 0.8) -> float:
    """>1 when more rechecks are due than one hour of page budget can handle (the rate never increases)."""
    capacity = max_pages_per_hour * recheck_share
    if capacity <= 0:
        return 1.0
    return max(1.0, due_count / capacity)
```

`vinted_tracker/outcome.py`:
```python
"""Decide an item's final status and sell time from its observations."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from .models import UNSOLD_FINAL, Status

_LIVE = {Status.AVAILABLE, Status.RESERVED}


@dataclass(frozen=True)
class Outcome:
    final_status: str | None
    sold_after_min: timedelta | None = None
    sold_after_max: timedelta | None = None
    uncertain: bool = False


def compute_outcome(
    uploaded_at: datetime,
    observations: list[tuple[datetime, Status]],
    now: datetime,
    *,
    stop_age: timedelta,
    uncertain_gap: timedelta,
) -> Outcome:
    seen = sorted((t, s) for t, s in observations if s is not Status.UNKNOWN)
    for index, (observed_at, status) in enumerate(seen):
        if status is Status.SOLD:
            live = [t for t, s in seen[:index] if s in _LIVE]
            last_live = live[-1] if live else uploaded_at
            return Outcome(
                final_status=Status.SOLD.value,
                sold_after_min=last_live - uploaded_at,
                sold_after_max=observed_at - uploaded_at,
                uncertain=(observed_at - last_live) > uncertain_gap,
            )
        if status is Status.DELETED:
            return Outcome(final_status=Status.DELETED.value, uncertain=True)
    if now - uploaded_at >= stop_age:
        last_status = seen[-1][1] if seen else None
        return Outcome(final_status=Status.HIDDEN.value if last_status is Status.HIDDEN else UNSOLD_FINAL)
    return Outcome(final_status=None)
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python -m pytest tests/test_schedule.py tests/test_outcome.py -v`
Expected: 16 passed.

- [ ] **Step 5: Commit**

```powershell
git add vinted_tracker/schedule.py vinted_tracker/outcome.py tests/test_schedule.py tests/test_outcome.py
git commit -m "Add recheck schedule and sell-time outcome logic"
```

- [ ] **Step 6: Controller: update progress page.** Phase 4 → `active`, note "Schedule + outcome logic done".

---

### Task 7: Browser session, rate limiter, challenge detection

**Files:**
- Create: `vinted_tracker/browser.py`, `tests/test_browser.py`

**Interfaces:**
- Consumes: `models.FetchedPage`, `models.utcnow`.
- Produces:
  - `browser.Fetcher` (Protocol: `fetch(url: str) -> FetchedPage`, attribute `pages_loaded: int`)
  - `browser.BlockedError`, `browser.FetchError`
  - `browser.is_challenge(status: int, html: str) -> bool`, `browser.should_block(resource_type: str, url: str) -> bool`
  - `browser.RateLimiter(min_delay_s, max_delay_s, max_per_hour, *, clock, sleep, rand)` with `.wait()`
  - `browser.BrowserSession(profile_dir: Path, limiter: RateLimiter, *, headless=True, retries=3)`, a context manager with `.fetch(url) -> FetchedPage` and `.pages_loaded`
  - `browser.save_debug_page(page: FetchedPage, label: str, debug_dir: Path) -> Path`

- [ ] **Step 1: Write the failing tests** in `tests/test_browser.py`

```python
from vinted_tracker.browser import RateLimiter, is_challenge, save_debug_page, should_block
from vinted_tracker.models import FetchedPage


class FakeClock:
    def __init__(self):
        self.t = 1000.0
        self.sleeps = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.t += seconds


def limiter(clock, lo=8, hi=12, per_hour=360, gap=10.0):
    return RateLimiter(lo, hi, per_hour, clock=clock.now, sleep=clock.sleep, rand=lambda a, b: gap)


def test_first_wait_does_not_sleep():
    clock = FakeClock()
    limiter(clock).wait()
    assert clock.sleeps == []


def test_waits_the_rest_of_the_random_gap():
    clock = FakeClock()
    lim = limiter(clock)
    lim.wait()
    clock.t += 3
    lim.wait()
    assert clock.sleeps == [7.0]


def test_no_sleep_when_gap_already_passed():
    clock = FakeClock()
    lim = limiter(clock)
    lim.wait()
    clock.t += 30
    lim.wait()
    assert clock.sleeps == []


def test_hourly_cap():
    clock = FakeClock()
    lim = limiter(clock, lo=1, hi=1, per_hour=3, gap=1.0)
    for _ in range(4):
        lim.wait()
    assert clock.sleeps == [1.0, 1.0, 1.0, 3597.0]


def test_is_challenge():
    assert is_challenge(403, "")
    assert is_challenge(429, "")
    assert is_challenge(200, '<iframe src="https://geo.captcha-delivery.com/captcha/?x=1"></iframe>')
    assert not is_challenge(200, "<html>ok</html>")
    assert not is_challenge(404, "<html>not found</html>")


def test_should_block():
    assert should_block("image", "https://images1.vinted.net/t/x.webp")
    assert should_block("font", "https://www.vinted.ro/font.woff2")
    assert should_block("script", "https://securepubads.g.doubleclick.net/tag/js/gpt.js")
    assert should_block("xhr", "https://fastlane.rubiconproject.com/a/api/fastlane.json")
    assert not should_block("document", "https://www.vinted.ro/items/1")
    assert not should_block("script", "https://www.vinted.ro/_next/static/chunk.js")


def test_save_debug_page(tmp_path):
    page = FetchedPage(url="https://www.vinted.ro/items/1", status=200, html="<html>x</html>", text="x")
    path = save_debug_page(page, "item-1", tmp_path)
    assert path.read_text(encoding="utf-8") == "<html>x</html>"
    assert path.with_suffix(".txt").read_text(encoding="utf-8").startswith("URL: https://www.vinted.ro/items/1")
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_browser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vinted_tracker.browser'`.

- [ ] **Step 3: Write `vinted_tracker/browser.py`**

```python
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
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python -m pytest tests/test_browser.py -v`
Expected: 7 passed.

- [ ] **Step 5: Live smoke check** (one real catalog page through the real session + parser)

```powershell
@'
from pathlib import Path
from vinted_tracker.browser import BrowserSession, RateLimiter
from vinted_tracker.parse import parse_catalog

with BrowserSession(Path("browser-profile"), RateLimiter(8, 12, 360)) as session:
    page = session.fetch("https://www.vinted.ro/catalog?catalog[]=5&brand_ids[]=73306&order=newest_first")
items = parse_catalog(page.html)
print(page.status, len(items), items[0].brand, items[0].price_ron)
'@ | .venv\Scripts\python -
```
Expected: something like `200 96 Stone Island 91.51`. If it raises `BlockedError`, stop and tell the user (do not retry in a loop).

- [ ] **Step 6: Commit**

```powershell
git add vinted_tracker/browser.py tests/test_browser.py
git commit -m "Add rate-limited browser session with challenge detection"
```

- [ ] **Step 7: Controller: update progress page.** Phase 3 → `active`, note "Browser session works live".

---

### Task 8: Harvest the spike: real fixtures, findings, parser confirmation

**Start only when the spike (Task 1) has run ≥ 24 h**, or has finished. If `spike\watch.log` shows no `sold_text: true` / `can_buy: "false"` transition yet, let it keep running and do Tasks 9–11 first, then come back.

**Files:**
- Create: `tests/fixtures/*.html.gz|.txt|.meta.json`, `tests/fixtures/expected.json`, `docs/spike-findings.md`
- Modify (only if findings require it): `vinted_tracker/parse.py` (`_status`, `_SOLD_RE`, the deleted check in `parse_item`, `_UPLOAD_RE`), the matching tests in `tests/test_parse_item.py` and the `item_page` helper, `config.yaml` (`headless`, `whole_price_prefilter`)

**Interfaces:**
- Produces: `tests/fixtures/expected.json` in this exact shape (values come from the snapshots you pick and verify by reading their `.txt`):
```json
{
  "catalog": {"file": "catalog", "min_items": 20,
              "first_item": {"id": 0, "brand": "", "size": "", "condition": "", "price_ron": "0"}},
  "items": [
    {"file": "item_available", "item_id": 0, "status": "available", "currency": "RON", "price": "0", "upload_age_minutes": 0},
    {"file": "item_foreign",   "item_id": 0, "status": "available", "currency": "PLN"},
    {"file": "item_sold",      "item_id": 0, "status": "sold"},
    {"file": "item_reserved",  "item_id": 0, "status": "reserved"},
    {"file": "item_deleted",   "item_id": 0, "status": "deleted"}
  ]
}
```
Every `0`/`""` above is replaced by the real value read from the chosen fixture. Leave out `item_reserved` if the spike never saw one, and say so in the findings.

- [ ] **Step 1: Stop the spike** (if still running) and list the state changes

```powershell
Get-Content spike\out\changes.jsonl | Select-Object -Last 60
```
Identify, per item id: its first (available) snapshot, a snapshot where `sold_text` is true, one where `is_reserved` is `"true"`, and one where `on_item_page` is false or `http` is 404 (deleted).

- [ ] **Step 2: Create the fixtures**

```powershell
.venv\Scripts\python spike\make_fixture.py spike/out/catalog catalog
.venv\Scripts\python spike\make_fixture.py spike/out/<id>-<stamp> item_available
.venv\Scripts\python spike\make_fixture.py spike/out/<id>-<stamp> item_foreign
.venv\Scripts\python spike\make_fixture.py spike/out/<id>-<stamp> item_sold
.venv\Scripts\python spike\make_fixture.py spike/out/<id>-<stamp> item_reserved
.venv\Scripts\python spike\make_fixture.py spike/out/<id>-<stamp> item_deleted
```
(`<id>-<stamp>` = the snapshot names picked in Step 1. `item_foreign` = any first snapshot whose `currency` is not RON.)

- [ ] **Step 3: Write `tests/fixtures/expected.json`** using the shape above. Read each fixture's `.txt` (and `.meta.json`) to verify every value by eye: status, currency, price, upload text.

- [ ] **Step 4: Run the fixture tests**

Run: `.venv\Scripts\python -m pytest tests/test_parse_fixtures.py -v`
Expected: all pass. If one fails, compare the page data with the assumptions in Task 5 and change **only** `_status`, `_SOLD_RE`, the deleted check or `_UPLOAD_RE`. Update the matching synthetic test and the `item_page` helper so they describe the real structure. Re-run `.venv\Scripts\python -m pytest -v` until everything passes.

- [ ] **Step 5: Check the price pre-filter**

Run: `.venv\Scripts\python spike\prefilter_check.py`
Expected output shape: `items=50 RON=.. foreign=..` and two counts. If "RON sellers WITH decimals" is more than 10% of RON sellers, set `whole_price_prefilter: false` in `config.yaml`.

- [ ] **Step 6: Write `docs/spike-findings.md`**. Sections: *Sold signal* (exact field/text), *Reserved*, *Deleted* (404 or redirect, final URL), *Headless* (blocked or not), *Foreign share* (RON vs foreign counts), *Price pre-filter* (the two counts and the decision), *Timing* (how fast items sold in the sample, if any). One or two sentences each, with the item IDs used as evidence.

- [ ] **Step 7: Commit**

```powershell
git add tests/fixtures docs/spike-findings.md config.yaml vinted_tracker/parse.py tests/test_parse_item.py tests/helpers.py
git commit -m "Add real page fixtures and Phase 0 spike findings"
```

- [ ] **Step 8: Controller: update progress page.** Phase 0 → `done`, Phase 2 → `done`. Add a log entry summarising the findings (sold signal, foreign share, pre-filter decision).

---

### Task 9: Discovery

**Files:**
- Create: `vinted_tracker/discover.py`, `tests/test_discover.py`

**Interfaces:**
- Consumes: `db.*` (Task 3), `parse.parse_catalog`, `parse.parse_item`, `parse.ParseError` (Tasks 4–5), `schedule.next_check_at` (Task 6), `browser.Fetcher`, `browser.save_debug_page` (Task 7), `config.Config`, `config.Query`.
- Produces:
  - `discover.build_catalog_url(base_url, q: Query, page=1) -> str`
  - `discover.item_url(base_url, item_id) -> str`
  - `discover.reject_reason(snap: ItemSnapshot, max_age: timedelta) -> str | None`
  - `discover.DiscoverResult(baseline, candidates, tracked, skipped, parse_errors)`
  - `discover.discover_query(conn, fetcher, cfg, q, clock: Callable[[], datetime], debug_dir: Path) -> DiscoverResult`

- [ ] **Step 1: Write the failing tests** in `tests/test_discover.py`

```python
from datetime import datetime, timedelta, timezone

from helpers import BASE, FakeFetcher, catalog_entry, catalog_html, catalog_page, item_page, make_config

from vinted_tracker import db
from vinted_tracker.config import Query
from vinted_tracker.discover import build_catalog_url, discover_query, item_url
from vinted_tracker.models import FetchedPage

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
Q = Query("streetwear", (5,), (53,))
CAT1 = build_catalog_url(BASE, Q)
CAT2 = build_catalog_url(BASE, Q, page=2)


def run(conn, fetcher, cfg=None, tmp_path=None):
    return discover_query(conn, fetcher, cfg or make_config(), Q, lambda: NOW, tmp_path)


def test_build_catalog_url():
    q = Query("x", (5,), (53, 14), 50.0, None)
    assert build_catalog_url(BASE, q) == (
        "https://www.vinted.ro/catalog?catalog[]=5&brand_ids[]=53&brand_ids[]=14&price_from=50&order=newest_first"
    )
    assert build_catalog_url(BASE, q, page=2).endswith("&order=newest_first&page=2")
    assert item_url(BASE, 7) == "https://www.vinted.ro/items/7"


def test_first_poll_only_sets_baseline(conn, tmp_path):
    fetcher = FakeFetcher({CAT1: catalog_page(CAT1, [300, 299, 298])})
    result = run(conn, fetcher, tmp_path=tmp_path)
    assert result.baseline is True
    assert db.get_query_state(conn, "streetwear") == (300, NOW)
    assert fetcher.calls == [CAT1]


def test_tracks_fresh_romanian_items_and_skips_the_rest(conn, tmp_path):
    db.set_query_state(conn, "streetwear", 298, NOW - timedelta(minutes=5))
    fetcher = FakeFetcher({
        CAT1: catalog_page(CAT1, [301, 300, 299, 298]),
        item_url(BASE, 299): item_page(299),
        item_url(BASE, 300): item_page(300, currency="PLN", amount="150"),
        item_url(BASE, 301): item_page(301, text="Încărcat acum 2 ore"),
    })
    result = run(conn, fetcher, tmp_path=tmp_path)
    assert (result.candidates, result.tracked, result.skipped) == (3, 1, 2)
    row = conn.execute("SELECT * FROM items WHERE id = 299").fetchone()
    assert row["uploaded_at"] == NOW - timedelta(minutes=3)
    assert row["next_check_at"] == NOW + timedelta(hours=2)
    assert row["query_name"] == "streetwear"
    reasons = {r["id"]: r["reason"] for r in conn.execute("SELECT id, reason FROM skipped_items").fetchall()}
    assert reasons == {300: "foreign_seller", 301: "too_old"}
    assert db.get_query_state(conn, "streetwear") == (301, NOW)


def test_fetches_page_two_when_all_of_page_one_is_new(conn, tmp_path):
    db.set_query_state(conn, "streetwear", 100, NOW - timedelta(minutes=5))
    pages = {CAT1: catalog_page(CAT1, [205, 204]), CAT2: catalog_page(CAT2, [203, 150, 99])}
    pages.update({item_url(BASE, i): item_page(i) for i in (150, 203, 204, 205)})
    result = run(conn, FakeFetcher(pages), tmp_path=tmp_path)
    assert result.tracked == 4


def test_known_items_are_not_refetched(conn, tmp_path):
    db.set_query_state(conn, "streetwear", 298, NOW - timedelta(minutes=5))
    db.add_skipped(conn, 300, "foreign_seller", NOW)
    fetcher = FakeFetcher({CAT1: catalog_page(CAT1, [300, 298])})  # 298 = high-water mark, so no page 2
    result = run(conn, fetcher, tmp_path=tmp_path)
    assert fetcher.calls == [CAT1]
    assert result.candidates == 0


def test_daily_cap_skips_without_fetching(conn, tmp_path):
    db.set_query_state(conn, "streetwear", 10, NOW - timedelta(minutes=5))
    fetcher = FakeFetcher({CAT1: catalog_page(CAT1, [12, 11, 10]), item_url(BASE, 11): item_page(11)})
    result = run(conn, fetcher, cfg=make_config(max_new_per_day=1), tmp_path=tmp_path)
    assert result.tracked == 1
    assert item_url(BASE, 12) not in fetcher.calls
    assert conn.execute("SELECT reason FROM skipped_items WHERE id = 12").fetchone()["reason"] == "daily_cap"


def test_decimal_price_prefilter_skips_without_fetching(conn, tmp_path):
    db.set_query_state(conn, "streetwear", 10, NOW - timedelta(minutes=5))
    page = FetchedPage(
        url=CAT1, status=200, html=catalog_html(catalog_entry(11, price="91.51"), catalog_entry(10)), text=""
    )
    fetcher = FakeFetcher({CAT1: page})
    result = run(conn, fetcher, tmp_path=tmp_path)
    assert fetcher.calls == [CAT1]
    assert result.skipped == 1
    assert conn.execute("SELECT reason FROM skipped_items WHERE id = 11").fetchone()["reason"] == "likely_foreign"


def test_catalog_parse_error_saves_debug_page(conn, tmp_path):
    fetcher = FakeFetcher({CAT1: FetchedPage(url=CAT1, status=200, html="<html>changed</html>", text="")})
    result = run(conn, fetcher, tmp_path=tmp_path)
    assert result.parse_errors == 1
    assert db.get_query_state(conn, "streetwear") is None
    assert len(list(tmp_path.glob("*catalog-streetwear-p1.html"))) == 1
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_discover.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vinted_tracker.discover'`.

- [ ] **Step 3: Write `vinted_tracker/discover.py`**

```python
"""Find brand-new listings for a watchlist query and start tracking the ones that qualify."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

import psycopg

from . import db
from .browser import Fetcher, save_debug_page
from .config import Config, Query
from .models import CatalogItem, ItemSnapshot, Status
from .parse import ParseError, parse_catalog, parse_item
from .schedule import next_check_at

log = logging.getLogger(__name__)


@dataclass
class DiscoverResult:
    baseline: bool = False
    candidates: int = 0
    tracked: int = 0
    skipped: int = 0
    parse_errors: int = 0


def build_catalog_url(base_url: str, q: Query, page: int = 1) -> str:
    params: list[tuple[str, object]] = [("catalog[]", c) for c in q.catalog_ids]
    params += [("brand_ids[]", b) for b in q.brand_ids]
    if q.price_from is not None:
        params.append(("price_from", _number(q.price_from)))
    if q.price_to is not None:
        params.append(("price_to", _number(q.price_to)))
    params.append(("order", "newest_first"))
    if page > 1:
        params.append(("page", page))
    return f"{base_url}/catalog?{urlencode(params, safe='[]')}"


def item_url(base_url: str, item_id: int) -> str:
    return f"{base_url}/items/{item_id}"


def reject_reason(snap: ItemSnapshot, max_age: timedelta) -> str | None:
    if snap.status is not Status.AVAILABLE:
        return f"status_{snap.status.value}"
    if snap.currency != "RON":
        return "foreign_seller"
    if snap.upload_age is None:
        return "no_upload_age"
    if snap.upload_age >= max_age:
        return "too_old"
    return None


def discover_query(
    conn: psycopg.Connection,
    fetcher: Fetcher,
    cfg: Config,
    q: Query,
    clock: Callable[[], datetime],
    debug_dir: Path,
) -> DiscoverResult:
    result = DiscoverResult()
    state = db.get_query_state(conn, q.name)
    items = _load_catalog(fetcher, cfg, q, 1, debug_dir, result)
    if items is None:
        return result
    if state is None:
        high_water = max((i.id for i in items), default=0)
        db.set_query_state(conn, q.name, high_water, clock())
        result.baseline = True
        log.info("query %s: baseline set at item %s; tracking starts next poll", q.name, high_water)
        return result

    high_water = state[0]
    if items and min(i.id for i in items) > high_water:
        items = items + (_load_catalog(fetcher, cfg, q, 2, debug_dir, result) or [])
    fresh = sorted({i.id: i for i in items if i.id > high_water}.values(), key=lambda i: i.id)
    for item in fresh:
        if db.is_known(conn, item.id):
            continue
        result.candidates += 1
        reason = _catalog_reject_reason(conn, cfg, item, clock())
        if reason is None:
            reason = _try_track(conn, fetcher, cfg, q, item, clock, debug_dir, result)
        if reason is not None:
            db.add_skipped(conn, item.id, reason, clock())
            result.skipped += 1
    db.set_query_state(conn, q.name, max([high_water] + [i.id for i in items]), clock())
    log.info(
        "query %s: %s candidates, %s tracked, %s skipped",
        q.name, result.candidates, result.tracked, result.skipped,
    )
    return result


def _load_catalog(
    fetcher: Fetcher, cfg: Config, q: Query, page_no: int, debug_dir: Path, result: DiscoverResult
) -> list[CatalogItem] | None:
    page = fetcher.fetch(build_catalog_url(cfg.base_url, q, page_no))
    try:
        return parse_catalog(page.html)
    except ParseError as exc:
        log.warning("query %s page %s: %s", q.name, page_no, exc)
        save_debug_page(page, f"catalog-{q.name}-p{page_no}", debug_dir)
        result.parse_errors += 1
        return None


def _catalog_reject_reason(conn: psycopg.Connection, cfg: Config, item: CatalogItem, now: datetime) -> str | None:
    if db.count_new_since(conn, now - timedelta(days=1)) >= cfg.max_new_per_day:
        return "daily_cap"
    price = item.price_ron
    if cfg.whole_price_prefilter and price is not None and price != price.to_integral_value():
        return "likely_foreign"
    return None


def _try_track(
    conn: psycopg.Connection,
    fetcher: Fetcher,
    cfg: Config,
    q: Query,
    item: CatalogItem,
    clock: Callable[[], datetime],
    debug_dir: Path,
    result: DiscoverResult,
) -> str | None:
    """Return a skip reason, or None if the item is now tracked."""
    page = fetcher.fetch(item_url(cfg.base_url, item.id))
    try:
        snap = parse_item(page, item.id)
    except ParseError as exc:
        log.warning("item %s: %s", item.id, exc)
        save_debug_page(page, f"item-{item.id}", debug_dir)
        result.parse_errors += 1
        return "parse_error"
    reason = reject_reason(snap, timedelta(minutes=cfg.max_item_age_minutes))
    if reason is not None:
        return reason
    now = clock()
    uploaded_at = now - snap.upload_age
    db.insert_item(
        conn,
        item=item,
        snap=snap,
        query_name=q.name,
        uploaded_at=uploaded_at,
        first_seen_at=now,
        next_check_at=next_check_at(uploaded_at, now, cfg.recheck_schedule),
    )
    result.tracked += 1
    return None


def _number(value: float) -> str:
    return str(int(value)) if float(value).is_integer() else str(value)
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python -m pytest tests/test_discover.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```powershell
git add vinted_tracker/discover.py tests/test_discover.py
git commit -m "Add discovery of new listings per watchlist query"
```

- [ ] **Step 6: Controller: update progress page.** Phase 3 → `done`.

---

### Task 10: Rechecks

**Files:**
- Create: `vinted_tracker/recheck.py`, `tests/test_recheck.py`

**Interfaces:**
- Consumes: `db.*`, `parse.parse_item`, `parse.ParseError`, `schedule.next_check_at`, `schedule.stop_age`, `outcome.compute_outcome`, `browser.Fetcher`, `browser.save_debug_page`, `discover.item_url`.
- Produces: `recheck.RecheckResult(status: Status, parse_error: bool, final_status: str | None)`, `recheck.recheck_item(conn, fetcher, cfg, row: dict, clock, debug_dir, stretch=1.0) -> RecheckResult` (`row` needs keys `id`, `uploaded_at`).

- [ ] **Step 1: Write the failing tests** in `tests/test_recheck.py`

```python
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from helpers import BASE, FakeFetcher, item_page, make_catalog_item, make_config, make_snapshot

from vinted_tracker import db
from vinted_tracker.discover import item_url
from vinted_tracker.models import FetchedPage, Status
from vinted_tracker.recheck import recheck_item

T0 = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
ROW = {"id": 1001, "uploaded_at": T0}
URL = item_url(BASE, 1001)


def track(conn):
    db.insert_item(
        conn, item=make_catalog_item(1001), snap=make_snapshot(1001), query_name="streetwear",
        uploaded_at=T0, first_seen_at=T0 + timedelta(minutes=5), next_check_at=T0 + timedelta(hours=2),
    )


def check(conn, page, hours, tmp_path, stretch=1.0):
    now = T0 + timedelta(hours=hours)
    return recheck_item(conn, FakeFetcher({URL: page}), make_config(), ROW, lambda: now, tmp_path, stretch)


def item_row(conn):
    return conn.execute("SELECT * FROM items WHERE id = 1001").fetchone()


def test_still_available_schedules_next_check(conn, tmp_path):
    track(conn)
    result = check(conn, item_page(1001), 2, tmp_path)
    assert (result.status, result.final_status, result.parse_error) == (Status.AVAILABLE, None, False)
    row = item_row(conn)
    assert row["next_check_at"] == T0 + timedelta(hours=4)
    assert row["last_checked_at"] == T0 + timedelta(hours=2)
    assert db.last_observation(conn, 1001)["raw"] is None  # unchanged status: no raw copy


def test_sold_sets_outcome_and_keeps_raw(conn, tmp_path):
    track(conn)
    result = check(conn, item_page(1001, can_buy=False, text="Vândut"), 2, tmp_path)
    assert result.final_status == "sold"
    row = item_row(conn)
    assert row["final_status"] == "sold"
    assert row["sold_after_min"] == timedelta(minutes=5)
    assert row["sold_after_max"] == timedelta(hours=2)
    assert row["next_check_at"] is None
    assert db.last_observation(conn, 1001)["raw"]["sold_text"] is True


def test_deleted_is_final(conn, tmp_path):
    track(conn)
    page = FetchedPage(url=f"{BASE}/catalog", status=200, html="<html></html>", text="")
    assert check(conn, page, 2, tmp_path).final_status == "deleted"
    assert item_row(conn)["uncertain"] is True


def test_parse_error_records_unknown_and_retries(conn, tmp_path):
    track(conn)
    page = FetchedPage(url=f"{BASE}/items/1001-x", status=200, html="<html>changed</html>", text="")
    result = check(conn, page, 2, tmp_path)
    assert result.parse_error is True
    assert db.last_observation(conn, 1001)["status"] == "unknown"
    assert item_row(conn)["next_check_at"] == T0 + timedelta(hours=4)
    assert len(list(tmp_path.glob("*item-1001.html"))) == 1


def test_price_drop_is_recorded(conn, tmp_path):
    track(conn)
    check(conn, item_page(1001, amount="60.0"), 2, tmp_path)
    assert db.last_observation(conn, 1001)["price_ron"] == Decimal("60.00")


def test_unsold_after_thirty_days(conn, tmp_path):
    track(conn)
    assert check(conn, item_page(1001), 720, tmp_path).final_status == "unsold_30d"


def test_stretch_delays_next_check(conn, tmp_path):
    track(conn)
    check(conn, item_page(1001), 2, tmp_path, stretch=2.0)
    assert item_row(conn)["next_check_at"] == T0 + timedelta(hours=6)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_recheck.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vinted_tracker.recheck'`.

- [ ] **Step 3: Write `vinted_tracker/recheck.py`**

```python
"""Re-check one tracked item and update its observations and outcome."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import psycopg

from . import db
from .browser import Fetcher, save_debug_page
from .config import Config
from .discover import item_url
from .models import ItemSnapshot, Status
from .outcome import compute_outcome
from .parse import ParseError, parse_item
from .schedule import next_check_at, stop_age

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class RecheckResult:
    status: Status
    parse_error: bool
    final_status: str | None


def recheck_item(
    conn: psycopg.Connection,
    fetcher: Fetcher,
    cfg: Config,
    row: dict,
    clock: Callable[[], datetime],
    debug_dir: Path,
    stretch: float = 1.0,
) -> RecheckResult:
    item_id, uploaded_at = row["id"], row["uploaded_at"]
    page = fetcher.fetch(item_url(cfg.base_url, item_id))
    now = clock()
    snap: ItemSnapshot | None
    try:
        snap = parse_item(page, item_id)
    except ParseError as exc:
        log.warning("item %s: %s", item_id, exc)
        save_debug_page(page, f"item-{item_id}", debug_dir)
        snap = None

    status = snap.status if snap is not None else Status.UNKNOWN
    previous = db.last_observation(conn, item_id)
    changed = snap is not None and (previous is None or previous["status"] != status.value)
    db.add_observation(
        conn,
        item_id,
        now,
        status,
        snap.price if snap is not None and snap.currency == "RON" else None,
        snap.favourite_count if snap is not None else None,
        snap.raw if changed else None,
    )

    schedule = cfg.recheck_schedule
    outcome = compute_outcome(
        uploaded_at,
        db.observations_for(conn, item_id),
        now,
        stop_age=stop_age(schedule),
        uncertain_gap=timedelta(hours=cfg.uncertain_gap_hours),
    )
    db.update_item_after_check(
        conn,
        item_id,
        checked_at=now,
        next_check_at=None if outcome.final_status else next_check_at(uploaded_at, now, schedule, stretch),
        final_status=outcome.final_status,
        sold_after_min=outcome.sold_after_min,
        sold_after_max=outcome.sold_after_max,
        uncertain=outcome.uncertain,
    )
    if outcome.final_status:
        log.info("item %s finished: %s", item_id, outcome.final_status)
    return RecheckResult(status=status, parse_error=snap is None, final_status=outcome.final_status)
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python -m pytest tests/test_recheck.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```powershell
git add vinted_tracker/recheck.py tests/test_recheck.py
git commit -m "Add item rechecks with outcome detection"
```

- [ ] **Step 6: Controller: update progress page.** Phase 4 → `done`.

---

### Task 11: Excel export

**Files:**
- Create: `vinted_tracker/export.py`, `tests/test_export.py`

**Interfaces:**
- Consumes: `db` tables (Task 3); helpers `make_catalog_item`, `make_snapshot`.
- Produces: `export.build_report(conn, base_url: str) -> dict[str, pandas.DataFrame]` with sheets `Items`, `By brand`, `By category`, `By size`, `By condition`, `By price band`, `Price drops`; `export.write_report(frames, path: Path) -> None`.

Summary columns per dimension: `<dimension>`, `tracked`, `sold`, `median_hours_to_sell`, `p25_hours`, `p75_hours`, `pct_sold_within_7d`, `pct_sold_within_30d`, `median_price_ron`, `avg_price_drop_pct_sold`. Medians use only `sold` and not `uncertain`. The sell-through denominators only count items at least 7 or 30 days old.

- [ ] **Step 1: Write the failing tests** in `tests/test_export.py`

```python
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pandas as pd
from helpers import make_catalog_item, make_snapshot

from vinted_tracker import db
from vinted_tracker.export import build_report, write_report
from vinted_tracker.models import Status

NOW = datetime.now(timezone.utc)
UPLOADED = NOW - timedelta(days=40)


def add(conn, item_id, brand, price, *, sold_hours=None, low_price=None):
    db.insert_item(
        conn,
        item=make_catalog_item(item_id, brand=brand, price_ron=Decimal(price)),
        snap=make_snapshot(item_id, price=Decimal(price)),
        query_name="q",
        uploaded_at=UPLOADED,
        first_seen_at=UPLOADED + timedelta(minutes=5),
        next_check_at=None,
    )
    if low_price is not None:
        db.add_observation(conn, item_id, UPLOADED + timedelta(hours=1), Status.AVAILABLE, Decimal(low_price), 0, None)
    if sold_hours is not None:
        low, high = sold_hours
        db.update_item_after_check(
            conn, item_id, checked_at=UPLOADED + timedelta(hours=high), next_check_at=None, final_status="sold",
            sold_after_min=timedelta(hours=low), sold_after_max=timedelta(hours=high), uncertain=False,
        )
    else:
        db.update_item_after_check(
            conn, item_id, checked_at=NOW, next_check_at=None, final_status="unsold_30d",
            sold_after_min=None, sold_after_max=None, uncertain=False,
        )


def seed(conn):
    add(conn, 1, "Nike", "80", sold_hours=(1, 3))
    add(conn, 2, "Nike", "120", sold_hours=(3, 5), low_price="100")
    add(conn, 3, "Nike", "450", sold_hours=(5, 7))
    add(conn, 4, "adidas", "60")


def test_brand_summary(conn):
    seed(conn)
    brand = build_report(conn, "https://www.vinted.ro")["By brand"].set_index("brand")
    assert brand.loc["Nike", "tracked"] == 3
    assert brand.loc["Nike", "sold"] == 3
    assert brand.loc["Nike", "median_hours_to_sell"] == 4.0
    assert brand.loc["Nike", "p25_hours"] == 3.0
    assert brand.loc["Nike", "p75_hours"] == 5.0
    assert brand.loc["Nike", "pct_sold_within_7d"] == 100.0
    assert brand.loc["Nike", "avg_price_drop_pct_sold"] == 5.6
    assert brand.loc["adidas", "sold"] == 0
    assert brand.loc["adidas", "pct_sold_within_30d"] == 0.0
    assert pd.isna(brand.loc["adidas", "median_hours_to_sell"])


def test_price_bands(conn):
    seed(conn)
    bands = build_report(conn, "https://www.vinted.ro")["By price band"].set_index("price_band")
    assert set(bands.index) == {"50-99 RON", "100-199 RON", "400+ RON"}
    assert bands.loc["50-99 RON", "tracked"] == 2


def test_items_and_price_drops(conn):
    seed(conn)
    frames = build_report(conn, "https://www.vinted.ro")
    items = frames["Items"].set_index("id")
    assert len(items) == 4
    assert items.loc[2, "sold_after_h"] == 4.0
    assert items.loc[2, "link"] == "https://www.vinted.ro/items/2-hanorac-nike"
    drops = frames["Price drops"]
    assert list(drops["id"]) == [2]
    assert drops.loc[0, "drop_pct"] == 16.7


def test_write_report(conn, tmp_path):
    seed(conn)
    frames = build_report(conn, "https://www.vinted.ro")
    path = tmp_path / "report.xlsx"
    write_report(frames, path)
    assert set(pd.read_excel(path, sheet_name=None)) == set(frames)
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_export.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'vinted_tracker.export'`.

- [ ] **Step 3: Write `vinted_tracker/export.py`**

```python
"""Excel report: one row per item plus sell-time summaries per brand, category, size, condition and price band."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import psycopg

PRICE_BAND_SQL = """CASE
    WHEN i.price_listed_ron IS NULL THEN '(none)'
    WHEN i.price_listed_ron < 50 THEN '0-49 RON'
    WHEN i.price_listed_ron < 100 THEN '50-99 RON'
    WHEN i.price_listed_ron < 200 THEN '100-199 RON'
    WHEN i.price_listed_ron < 400 THEN '200-399 RON'
    ELSE '400+ RON' END"""

DIMENSIONS = {
    "By brand": ("coalesce(i.brand, '(none)')", "brand"),
    "By category": ("coalesce(i.catalog_id::text, '(none)')", "catalog_id"),
    "By size": ("coalesce(i.size, '(none)')", "size"),
    "By condition": ("coalesce(i.condition, '(none)')", "condition"),
    "By price band": (PRICE_BAND_SQL, "price_band"),
}

ITEMS_SQL = """
SELECT i.id, i.title, i.brand, i.catalog_id, i.size, i.condition,
       i.price_listed_ron::float8 AS price_listed_ron,
       lp.lowest_price_ron,
       (i.uploaded_at AT TIME ZONE 'Europe/Bucharest') AS uploaded_at,
       coalesce(i.final_status, 'tracking') AS status,
       round((extract(epoch FROM i.sold_after_min) / 3600)::numeric, 1)::float8 AS sold_after_min_h,
       round((extract(epoch FROM i.sold_after_max) / 3600)::numeric, 1)::float8 AS sold_after_max_h,
       round((extract(epoch FROM (i.sold_after_min + i.sold_after_max) / 2) / 3600)::numeric, 1)::float8
           AS sold_after_h,
       i.uncertain, i.query_name,
       %(base)s || i.url AS link
FROM items i
LEFT JOIN LATERAL (
    SELECT min(o.price_ron)::float8 AS lowest_price_ron FROM observations o WHERE o.item_id = i.id
) lp ON true
ORDER BY i.uploaded_at DESC
"""

SUMMARY_SQL = """
WITH base AS (
    SELECT {expr} AS grp,
           i.final_status, i.uncertain, i.price_listed_ron,
           (extract(epoch FROM (i.sold_after_min + i.sold_after_max) / 2) / 3600)::float8 AS sold_h,
           now() - i.uploaded_at AS age,
           (SELECT min(o.price_ron) FROM observations o WHERE o.item_id = i.id) AS lowest_price
    FROM items i
)
SELECT grp AS "{label}",
       count(*) AS tracked,
       count(*) FILTER (WHERE final_status = 'sold') AS sold,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY sold_h)
              FILTER (WHERE final_status = 'sold' AND NOT uncertain))::numeric, 1)::float8 AS median_hours_to_sell,
       round((percentile_cont(0.25) WITHIN GROUP (ORDER BY sold_h)
              FILTER (WHERE final_status = 'sold' AND NOT uncertain))::numeric, 1)::float8 AS p25_hours,
       round((percentile_cont(0.75) WITHIN GROUP (ORDER BY sold_h)
              FILTER (WHERE final_status = 'sold' AND NOT uncertain))::numeric, 1)::float8 AS p75_hours,
       round(100.0 * count(*) FILTER (WHERE final_status = 'sold' AND sold_h <= 168 AND age >= interval '7 days')
             / NULLIF(count(*) FILTER (WHERE age >= interval '7 days'), 0), 1)::float8 AS pct_sold_within_7d,
       round(100.0 * count(*) FILTER (WHERE final_status = 'sold' AND sold_h <= 720 AND age >= interval '30 days')
             / NULLIF(count(*) FILTER (WHERE age >= interval '30 days'), 0), 1)::float8 AS pct_sold_within_30d,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY price_listed_ron::float8))::numeric, 2)::float8
           AS median_price_ron,
       round(avg(100.0 * (price_listed_ron - lowest_price) / NULLIF(price_listed_ron, 0))
             FILTER (WHERE final_status = 'sold'), 1)::float8 AS avg_price_drop_pct_sold
FROM base
GROUP BY grp
ORDER BY tracked DESC, grp
"""

PRICE_DROPS_SQL = """
SELECT i.id, i.title, i.brand,
       i.price_listed_ron::float8 AS listed_ron,
       min(o.price_ron)::float8 AS lowest_ron,
       round(100.0 * (i.price_listed_ron - min(o.price_ron)) / NULLIF(i.price_listed_ron, 0), 1)::float8 AS drop_pct,
       coalesce(i.final_status, 'tracking') AS status
FROM items i
JOIN observations o ON o.item_id = i.id
GROUP BY i.id
HAVING min(o.price_ron) < i.price_listed_ron
ORDER BY drop_pct DESC
"""


def build_report(conn: psycopg.Connection, base_url: str) -> dict[str, pd.DataFrame]:
    frames = {"Items": _frame(conn, ITEMS_SQL, {"base": base_url})}
    for sheet, (expr, label) in DIMENSIONS.items():
        frames[sheet] = _frame(conn, SUMMARY_SQL.format(expr=expr, label=label))
    frames["Price drops"] = _frame(conn, PRICE_DROPS_SQL)
    return frames


def write_report(frames: dict[str, pd.DataFrame], path: Path) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet, frame in frames.items():
            frame.to_excel(writer, sheet_name=sheet[:31], index=False)
        for worksheet in writer.book.worksheets:
            for column in worksheet.columns:
                width = max((len(str(cell.value)) for cell in column if cell.value is not None), default=8)
                worksheet.column_dimensions[column[0].column_letter].width = min(60, width + 2)


def _frame(conn: psycopg.Connection, sql: str, params: dict | None = None) -> pd.DataFrame:
    cur = conn.execute(sql, params)
    columns = [d.name for d in cur.description]
    return pd.DataFrame(cur.fetchall(), columns=columns)
```

- [ ] **Step 4: Run the tests**

Run: `.venv\Scripts\python -m pytest tests/test_export.py -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```powershell
git add vinted_tracker/export.py tests/test_export.py
git commit -m "Add Excel report with sell-time summaries"
```

- [ ] **Step 6: Controller: update progress page.** Phase 6 → `done`.

---

### Task 12: Runner loop, health, CLI

**Files:**
- Create: `vinted_tracker/runner.py`, `vinted_tracker/__main__.py`, `tests/test_runner.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above.
- Produces:
  - `runner.Runner(conn, fetcher, cfg, *, clock=utcnow, sleep=time.sleep, status_path=Path("status.json"), debug_dir=Path("debug"))` with `.tick() -> float` (seconds to wait), `.run_forever(max_ticks=None)`, `.write_status()`, `.health` (`starting|ok|blocked|parser_broken`)
  - `__main__.main(argv=None) -> int`, `__main__.build_parser()`, `__main__.save_fixture(page, name, directory=Path("tests/fixtures"))`
  - CLI: `python -m vinted_tracker [--config config.yaml] {run [--headed] [--max-ticks N] | init-db | status | export [--out FILE] | probe URL [--save-as NAME] [--headed]}`

- [ ] **Step 1: Write the failing tests**

`tests/test_runner.py`:
```python
import json
from datetime import datetime, timedelta, timezone

from helpers import BASE, BlockingFetcher, FakeFetcher, catalog_page, make_catalog_item, make_config, make_snapshot

from vinted_tracker import db
from vinted_tracker.config import Query
from vinted_tracker.discover import build_catalog_url
from vinted_tracker.runner import Runner

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)
Q = Query("streetwear", (5,), (53,))


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


def make_runner(conn, fetcher, tmp_path, clock=None, sleeps=None):
    return Runner(
        conn, fetcher, make_config(), clock=clock or Clock(NOW),
        sleep=(sleeps.append if sleeps is not None else lambda s: None),
        status_path=tmp_path / "status.json", debug_dir=tmp_path / "debug",
    )


def test_first_tick_sets_discovery_baseline(conn, tmp_path):
    url = build_catalog_url(BASE, Q)
    runner = make_runner(conn, FakeFetcher({url: catalog_page(url, [300, 299])}), tmp_path)
    assert runner.tick() == 0.0
    assert db.get_query_state(conn, "streetwear") == (300, NOW)
    assert runner.health == "ok"


def test_idle_tick_waits_for_next_event(conn, tmp_path):
    db.set_query_state(conn, "streetwear", 100, NOW - timedelta(minutes=1))
    runner = make_runner(conn, FakeFetcher(), tmp_path)
    assert runner.tick() == 60.0
    db.insert_item(
        conn, item=make_catalog_item(5), snap=make_snapshot(5), query_name="streetwear",
        uploaded_at=NOW - timedelta(minutes=10), first_seen_at=NOW - timedelta(minutes=5),
        next_check_at=NOW + timedelta(seconds=30),
    )
    assert runner.tick() == 30.0


def test_blocked_backs_off_and_reports(conn, tmp_path):
    sleeps = []
    runner = make_runner(conn, BlockingFetcher(), tmp_path, sleeps=sleeps)
    runner.run_forever(max_ticks=5)
    assert sleeps == [1800.0, 3600.0, 7200.0, 14400.0, 14400.0]
    status = json.loads((tmp_path / "status.json").read_text(encoding="utf-8"))
    assert status["health"] == "blocked"
    assert "challenge" in status["last_error"]
    assert conn.execute("SELECT blocks FROM runs").fetchone()["blocks"] == 5


def test_parser_broken_health_clears_after_an_hour(conn, tmp_path):
    clock = Clock(NOW)
    runner = make_runner(conn, FakeFetcher(), tmp_path, clock=clock)
    runner._record_parse_errors(10)
    runner._mark_ok()
    assert runner.health == "parser_broken"
    clock.t = NOW + timedelta(hours=2)
    runner._mark_ok()
    assert runner.health == "ok"
```

`tests/test_cli.py`:
```python
import pytest
from helpers import load_fixture

from vinted_tracker.__main__ import build_parser, save_fixture
from vinted_tracker.models import FetchedPage


def test_parser_requires_a_command():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_parser_reads_run_options():
    args = build_parser().parse_args(["--config", "x.yaml", "run", "--headed", "--max-ticks", "3"])
    assert (args.config, args.cmd, args.headed, args.max_ticks) == ("x.yaml", "run", True, 3)


def test_save_fixture_roundtrip(tmp_path):
    page = FetchedPage(url="https://www.vinted.ro/items/1-x", status=200, html="<html>ă</html>", text="Încărcat acum 3 minute")
    save_fixture(page, "sample", tmp_path)
    assert load_fixture("sample", tmp_path) == page
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python -m pytest tests/test_runner.py tests/test_cli.py -v`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Write `vinted_tracker/runner.py`**

```python
"""Main loop: alternate discovery and rechecks, back off when blocked, report health to status.json."""
from __future__ import annotations

import json
import logging
import time
from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

import psycopg

from . import db
from .browser import BlockedError, Fetcher, FetchError
from .config import Config
from .discover import discover_query
from .models import utcnow
from .recheck import recheck_item
from .schedule import stretch_factor

log = logging.getLogger(__name__)

PARSER_BROKEN_THRESHOLD = 10  # parse errors within one hour
MAX_IDLE_S = 60.0


@dataclass
class Counters:
    items_discovered: int = 0
    items_rechecked: int = 0
    blocks: int = 0
    parse_errors: int = 0


class Runner:
    def __init__(
        self,
        conn: psycopg.Connection,
        fetcher: Fetcher,
        cfg: Config,
        *,
        clock: Callable[[], datetime] = utcnow,
        sleep: Callable[[float], None] = time.sleep,
        status_path: Path = Path("status.json"),
        debug_dir: Path = Path("debug"),
    ) -> None:
        self.conn, self.fetcher, self.cfg = conn, fetcher, cfg
        self.clock, self.sleep = clock, sleep
        self.status_path, self.debug_dir = status_path, debug_dir
        self.counters = Counters()
        self.health = "starting"
        self.last_error: str | None = None
        self._block_level = 0
        self._parse_error_times: deque[datetime] = deque()

    def tick(self) -> float:
        """Do one unit of work. Returns how many seconds to wait before the next tick."""
        now = self.clock()
        poll = timedelta(minutes=self.cfg.poll_minutes)
        for q in self.cfg.queries:
            state = db.get_query_state(self.conn, q.name)
            if state is None or now - state[1] >= poll:
                result = discover_query(self.conn, self.fetcher, self.cfg, q, self.clock, self.debug_dir)
                self.counters.items_discovered += result.tracked
                self._record_parse_errors(result.parse_errors)
                self._mark_ok()
                return 0.0
        due = db.due_items(self.conn, now, limit=1)
        if due:
            stretch = stretch_factor(db.count_due(self.conn, now), self.cfg.max_pages_per_hour)
            result = recheck_item(self.conn, self.fetcher, self.cfg, due[0], self.clock, self.debug_dir, stretch)
            self.counters.items_rechecked += 1
            self._record_parse_errors(1 if result.parse_error else 0)
            self._mark_ok()
            return 0.0
        return self._seconds_until_next(now)

    def run_forever(self, max_ticks: int | None = None) -> None:
        run_id = db.start_run(self.conn, self.clock())
        ticks = 0
        try:
            while max_ticks is None or ticks < max_ticks:
                ticks += 1
                try:
                    wait = self.tick()
                except BlockedError as exc:
                    self._back_off(exc)
                    continue
                except FetchError as exc:
                    log.warning("%s", exc)
                    self.last_error = str(exc)
                    wait = MAX_IDLE_S
                self.write_status()
                if wait > 0:
                    self.sleep(wait)
        finally:
            try:
                db.finish_run(
                    self.conn, run_id, self.clock(),
                    pages_loaded=getattr(self.fetcher, "pages_loaded", 0), **asdict(self.counters),
                )
            except psycopg.Error:
                log.exception("could not record run statistics")

    def write_status(self) -> None:
        data = {
            "health": self.health,
            "updated_at": self.clock().isoformat(),
            "counts": db.status_counts(self.conn),
            "pages_loaded": getattr(self.fetcher, "pages_loaded", 0),
            "this_run": asdict(self.counters),
            "parse_errors_last_hour": len(self._parse_error_times),
            "last_error": self.last_error,
        }
        tmp = self.status_path.with_name(self.status_path.name + ".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        tmp.replace(self.status_path)

    def _back_off(self, exc: BlockedError) -> None:
        steps = self.cfg.backoff_minutes
        minutes = steps[min(self._block_level, len(steps) - 1)]
        self._block_level += 1
        self.counters.blocks += 1
        self.health = "blocked"
        self.last_error = str(exc)
        log.warning("Blocked by Vinted (%s). Pausing %.0f minutes. Captchas are never solved.", exc, minutes)
        self.write_status()
        self.sleep(minutes * 60)

    def _record_parse_errors(self, count: int) -> None:
        now = self.clock()
        self._parse_error_times.extend([now] * count)
        self.counters.parse_errors += count

    def _mark_ok(self) -> None:
        cutoff = self.clock() - timedelta(hours=1)
        while self._parse_error_times and self._parse_error_times[0] < cutoff:
            self._parse_error_times.popleft()
        self._block_level = 0
        if len(self._parse_error_times) >= PARSER_BROKEN_THRESHOLD:
            if self.health != "parser_broken":
                log.error("Many parse errors in the last hour: Vinted probably changed its pages. See debug/.")
            self.health = "parser_broken"
        else:
            self.health = "ok"

    def _seconds_until_next(self, now: datetime) -> float:
        waits = [MAX_IDLE_S]
        poll = timedelta(minutes=self.cfg.poll_minutes)
        for q in self.cfg.queries:
            state = db.get_query_state(self.conn, q.name)
            if state is not None:
                waits.append((state[1] + poll - now).total_seconds())
        next_due = db.next_due_at(self.conn)
        if next_due is not None:
            waits.append((next_due - now).total_seconds())
        return max(1.0, min(waits))
```

- [ ] **Step 4: Write `vinted_tracker/__main__.py`**

```python
"""Command line: python -m vinted_tracker <command>."""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import re
import sys
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path

import psycopg
from dotenv import load_dotenv

from . import db
from .browser import BlockedError, BrowserSession, RateLimiter
from .config import Config, ConfigError, load_config
from .export import build_report, write_report
from .models import FetchedPage
from .parse import ParseError, parse_catalog, parse_item
from .runner import Runner

PROFILE_DIR = Path("browser-profile")
FIXTURES_DIR = Path("tests/fixtures")
STATUS_PATH = Path("status.json")
_ITEM_ID_RE = re.compile(r"/items/(\d+)")
log = logging.getLogger("vinted_tracker")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="vinted_tracker", description="Vinted sell-time tracker")
    parser.add_argument("--config", default="config.yaml")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="run the tracker until stopped")
    run.add_argument("--headed", action="store_true", help="show the browser window")
    run.add_argument("--max-ticks", type=int, default=None, help="stop after N loop steps (testing)")
    sub.add_parser("init-db", help="create the database tables")
    sub.add_parser("status", help="show health and counts")
    export = sub.add_parser("export", help="write the Excel report")
    export.add_argument("--out", default="vinted_report.xlsx")
    probe = sub.add_parser("probe", help="fetch one page and show what the parser reads")
    probe.add_argument("url")
    probe.add_argument("--save-as", default=None, help="also save it as a test fixture with this name")
    probe.add_argument("--headed", action="store_true")
    return parser


def setup_logging() -> None:
    Path("logs").mkdir(exist_ok=True)
    handlers = [
        logging.StreamHandler(),
        RotatingFileHandler("logs/tracker.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8"),
    ]
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)


def save_fixture(page: FetchedPage, name: str, directory: Path = FIXTURES_DIR) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.html.gz").write_bytes(gzip.compress(page.html.encode("utf-8")))
    (directory / f"{name}.txt").write_text(page.text, encoding="utf-8")
    (directory / f"{name}.meta.json").write_text(json.dumps({"url": page.url, "status": page.status}, indent=2), encoding="utf-8")


def _browser(cfg: Config, headed: bool) -> BrowserSession:
    limiter = RateLimiter(cfg.min_delay_s, cfg.max_delay_s, cfg.max_pages_per_hour)
    return BrowserSession(PROFILE_DIR, limiter, headless=cfg.headless and not headed)


def cmd_run(cfg: Config, args: argparse.Namespace) -> int:
    with _browser(cfg, args.headed) as browser:
        while True:
            try:
                conn = db.connect(cfg.database_url)
                db.init_schema(conn)
                Runner(conn, browser, cfg, status_path=STATUS_PATH).run_forever(max_ticks=args.max_ticks)
                return 0
            except psycopg.OperationalError as exc:
                log.error("Database unreachable (%s). Scraping is paused; retrying in 60 s.", exc)
                time.sleep(60)


def cmd_init_db(cfg: Config, args: argparse.Namespace) -> int:
    db.init_schema(db.connect(cfg.database_url))
    print("Database tables are ready.")
    return 0


def cmd_status(cfg: Config, args: argparse.Namespace) -> int:
    if STATUS_PATH.exists():
        print(STATUS_PATH.read_text(encoding="utf-8"))
    else:
        print("No status.json yet: the tracker has not run.")
    print("Items by status:", db.status_counts(db.connect(cfg.database_url)))
    return 0


def cmd_export(cfg: Config, args: argparse.Namespace) -> int:
    frames = build_report(db.connect(cfg.database_url), cfg.base_url)
    write_report(frames, Path(args.out))
    print(f"Wrote {args.out} ({len(frames['Items'])} items).")
    return 0


def cmd_probe(cfg: Config, args: argparse.Namespace) -> int:
    try:
        with _browser(cfg, args.headed) as browser:
            page = browser.fetch(args.url)
    except BlockedError as exc:
        print(f"Blocked by Vinted: {exc}. Not retrying.")
        return 1
    print(f"HTTP {page.status}  final URL: {page.url}")
    match = _ITEM_ID_RE.search(args.url)
    try:
        if match:
            snap = parse_item(page, int(match.group(1)))
            print(
                f"status={snap.status.value} price={snap.price} {snap.currency} "
                f"favourites={snap.favourite_count} catalog_id={snap.catalog_id} upload_age={snap.upload_age}"
            )
        else:
            items = parse_catalog(page.html)
            print(f"{len(items)} catalog items")
            for item in items[:10]:
                print(f"  {item.id}  {item.price_ron} RON  {item.brand} | {item.size} | {item.condition} | {item.title}")
    except ParseError as exc:
        print(f"Parse error: {exc}")
    if args.save_as:
        save_fixture(page, args.save_as)
        print(f"Saved fixture tests/fixtures/{args.save_as}.*")
    return 0


COMMANDS = {"run": cmd_run, "init-db": cmd_init_db, "status": cmd_status, "export": cmd_export, "probe": cmd_probe}


def main(argv: list[str] | None = None) -> int:
    load_dotenv()
    args = build_parser().parse_args(argv)
    setup_logging()
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        print(f"Config error: {exc}", file=sys.stderr)
        return 2
    try:
        return COMMANDS[args.cmd](cfg, args)
    except KeyboardInterrupt:
        print("Stopped.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run the tests**

Run: `.venv\Scripts\python -m pytest tests/test_runner.py tests/test_cli.py -v`
Expected: 7 passed.

- [ ] **Step 6: Run the full suite**

Run: `.venv\Scripts\python -m pytest -v`
Expected: all pass (fixture tests pass if Task 8 is done, otherwise they're skipped).

- [ ] **Step 7: Live end-to-end run** (short, real site, real database)

```powershell
.venv\Scripts\python -m vinted_tracker init-db
.venv\Scripts\python -m vinted_tracker run --max-ticks 6
.venv\Scripts\python -m vinted_tracker status
```
Expected: the log shows three `baseline set` lines (one per query), then later ticks show `candidates/tracked/skipped` counts. `status` prints `"health": "ok"`. If health is `blocked`, stop and tell the user (no retries).

- [ ] **Step 8: Commit**

```powershell
git add vinted_tracker/runner.py vinted_tracker/__main__.py tests/test_runner.py tests/test_cli.py
git commit -m "Add runner loop with backoff and health, plus CLI"
```

- [ ] **Step 9: Controller: update progress page.** Phase 5 → `done`. Fill `stats` from `python -m vinted_tracker status` (for example `{"Tracking": n, "Sold": n, "Deleted": n, "Pages loaded": n}`).

---

### Task 13: Unattended running, deployment files, README, push

**Files:**
- Create: `scripts/run_tracker.ps1`, `scripts/register_task.ps1`, `Dockerfile`, `docker-compose.yml`, `.dockerignore`, `README.md`

**Interfaces:**
- Consumes: the CLI from Task 12.
- Produces: a Windows scheduled task `VintedTracker` (registered only with the user's OK); container files for the VPS (untested locally, since Docker isn't installed here).

- [ ] **Step 1: Write `scripts/run_tracker.ps1`**

```powershell
# Runs the tracker and restarts it if it ever exits (crash, reboot of the DB, etc.).
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)
while ($true) {
    & .\.venv\Scripts\python.exe -m vinted_tracker run
    Start-Sleep -Seconds 60
}
```

- [ ] **Step 2: Write `scripts/register_task.ps1`**

```powershell
# Registers a Windows scheduled task that starts the tracker when you log on.
$root = Split-Path -Parent $PSScriptRoot
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$root\scripts\run_tracker.ps1`"" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "VintedTracker" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Vinted sell-time tracker" -Force
Write-Host "Registered. Start now with: Start-ScheduledTask -TaskName VintedTracker"
```

- [ ] **Step 3: Write `Dockerfile`, `.dockerignore`, `docker-compose.yml`**

`Dockerfile`:
```dockerfile
FROM python:3.13-slim
WORKDIR /app
COPY pyproject.toml ./
COPY vinted_tracker ./vinted_tracker
RUN pip install --no-cache-dir . && python -m playwright install --with-deps chromium
COPY config.yaml ./
CMD ["python", "-m", "vinted_tracker", "run"]
```

`.dockerignore`:
```
.venv
.git
.env
browser-profile
spike
debug
logs
tests
docs
*.xlsx
status.json
```

`docker-compose.yml`:
```yaml
services:
  db:
    image: postgres:18
    environment:
      POSTGRES_USER: vinted
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:?set POSTGRES_PASSWORD in .env}
      POSTGRES_DB: vinted_tracker
    volumes:
      - pgdata:/var/lib/postgresql
    restart: unless-stopped
  tracker:
    build: .
    depends_on:
      - db
    environment:
      DATABASE_URL: postgresql://vinted:${POSTGRES_PASSWORD}@db:5432/vinted_tracker
    volumes:
      - ./debug:/app/debug
      - ./logs:/app/logs
      - ./browser-profile:/app/browser-profile
    restart: unless-stopped
volumes:
  pgdata: {}
```

- [ ] **Step 4: Write `README.md`**

````markdown
# Vinted Sell-Time Tracker

Tracks how long brand-new men's listings from Romanian sellers on vinted.ro take to sell,
and exports an Excel report by brand, category, size, condition and price band.

## Setup (Windows)

1. PostgreSQL: create the role and databases (once, in SQL Shell as `postgres`):
   ```sql
   CREATE USER vinted WITH PASSWORD 'your-password';
   CREATE DATABASE vinted_tracker OWNER vinted;
   CREATE DATABASE vinted_tracker_test OWNER vinted;
   ```
2. `Copy-Item .env.example .env` and put the password in `.env`.
3. Python environment:
   ```powershell
   python -m venv .venv
   .venv\Scripts\python -m pip install -e ".[dev]"
   .venv\Scripts\python -m playwright install chromium
   .venv\Scripts\python -m vinted_tracker init-db
   ```

## Use

| Command | What it does |
|---|---|
| `.venv\Scripts\python -m vinted_tracker run` | Runs the tracker until you stop it (Ctrl+C) |
| `.venv\Scripts\python -m vinted_tracker status` | Health (`ok`, `blocked`, `parser_broken`) and item counts |
| `.venv\Scripts\python -m vinted_tracker export` | Writes `vinted_report.xlsx` |
| `.venv\Scripts\python -m vinted_tracker probe <url>` | Fetches one page and shows what the parser reads |

Edit `config.yaml` to change the watchlist (brand IDs), check schedule or rate limits.

## Run unattended

`powershell -ExecutionPolicy Bypass -File scripts\register_task.ps1` starts the tracker at every logon.
Remove it with `Unregister-ScheduledTask -TaskName VintedTracker`.

## Move to a server later

Copy the repo and `.env` (with `POSTGRES_PASSWORD`) to the VPS, then `docker compose up -d --build`.
Move existing data with `pg_dump -Fc vinted_tracker > tracker.dump` locally and `pg_restore` on the server.

## Behaviour you should know

- It waits 8–12 s between pages and loads at most 360 pages an hour.
- If Vinted shows a captcha or blocks it, it stops and waits (30 min, then 1 h, 2 h, 4 h). It never solves captchas.
- Pages it can't read are saved to `debug/`. Many of them in an hour means Vinted changed its site (`status` shows `parser_broken`).
````

- [ ] **Step 5: Verify the scripts parse and ask before registering**

```powershell
$null = [System.Management.Automation.Language.Parser]::ParseFile("$PWD\scripts\run_tracker.ps1", [ref]$null, [ref]$null)
$null = [System.Management.Automation.Language.Parser]::ParseFile("$PWD\scripts\register_task.ps1", [ref]$null, [ref]$null)
"scripts parse OK"
```
Expected: `scripts parse OK`. Then **ask the user** whether to register the scheduled task now. Run `scripts\register_task.ps1` only on a yes.

- [ ] **Step 6: Commit and push**

```powershell
git add scripts Dockerfile .dockerignore docker-compose.yml README.md
git commit -m "Add unattended running, container files and README"
git push -u origin main
```
Expected: the push succeeds. If it fails with an authentication error, remind the user to run `git config --global credential.helper manager` and sign in, then retry the push once they confirm.

- [ ] **Step 7: Controller: update progress page.** Phase 7 → `done`. `now` → "Tracker running; next: collect data for a few weeks". Add stats.

---

## Progress page updates (controller only)

After each task, the main session updates https://claude.ai/artifact/5TZhDzeGjVt8wVTDqWcpj3:

1. Get the real time: `(Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")`.
2. `Artifact` → `action: "read_db"`, `db_op: "get"`, `collection: "progress"`, `doc_id: "build"`. Note `version`.
3. `Artifact` → `action: "write_db"`, `db_op: "update"`, same doc, `if_version: <version>`, with the whole `phases` array (change only the affected phase's `status`/`note`), `now` (`status`, `title`, `detail`), `updatedAt`, and `log` with the new entry first (keep at most 40 entries). Set `stats` once the tracker is running.

Phase IDs: `p0` = Tasks 1 + 8, `p1` = Tasks 2–3, `p2` = Tasks 4–5 (+ 8), `p3` = Tasks 7 + 9, `p4` = Tasks 6 + 10, `p5` = Task 12, `p6` = Task 11, `p7` = Task 13. Plan stage `plan` → `done` when the user approves this plan.
