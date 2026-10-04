# Vinted Tracker Dashboard — Design

Date: 2026-10-05
Status: Draft, awaiting review
Builds on: `docs/superpowers/specs/2026-09-27-vinted-sell-time-tracker-design.md` (the tracker)

## 1. Goal

A web dashboard for the running sell-time tracker where the owner can:

1. see the stats at a glance (counts, time-to-sell, charts),
2. watch the live status of every tracked listing,
3. download the Excel report,
4. change what the tracker follows (brand groups, product types, sizes, conditions) without editing files or restarting anything.

It runs locally for now and moves to the Hetzner CX22 with the tracker afterwards (separate project: Docker + login).

### Decisions from brainstorming

| Topic | Decision |
|---|---|
| Access | Local only for now: `http://localhost:8000`, bound to `127.0.0.1`. Login and HTTPS are added at the Hetzner step. |
| Layout | **One page** (option B): status bar, number tiles, charts, live product table. Settings open in a side panel. |
| Download | The existing Excel report (`.xlsx`), same content as `python -m vinted_tracker export`. |
| Stack | Python **FastAPI** + **Jinja2** templates + **htmx** (live refresh) + **Chart.js**. htmx and Chart.js are vendored as static files, with no CDN. |
| Settings editable in the UI | Brand groups (add/remove brands via Vinted search, add/rename/remove groups), product types, sizes (letter + waist), conditions. |
| Settings not in the UI | Check schedule, rate limits, daily cap, backoff. These stay in `config.yaml`. |
| Effect of a settings change | Applies to **new** listings within ~5 min. Listings already tracked carry on until finished. |

## 2. Vinted reference data (probed 2026-10-04)

**Product types** (children of 2050 "Haine", men's clothing):

| id | type | id | type |
|---|---|---|---|
| 257 | Blugi | 80 | Pantaloni scurți |
| 1206 | Îmbrăcăminte de exterior | 85 | Șosete și lenjerie intimă |
| 76 | Topuri și tricouri | 2910 | Haine de dormit |
| 32 | Costume și blazere | 84 | Costume de baie |
| 79 | Pulovere | 30 | Îmbrăcăminte pentru sport |
| 34 | Pantaloni | 92 | Costume și ținute speciale |
|  |  | 83 | Alte articole de îmbrăcăminte |

**Sizes** (`/api/v2/size_groups?catalog_ids=2050`):
- Letter (group 14): 206 XS, 207 S, 208 M, 209 L, 210 XL, 211 XXL, 212 XXXL, 308 4XL, 309 5XL, 1192 6XL, 1193 7XL, 1194 8XL.
- Waist (group 77): 1636 "44 | W28", 1638 "46 | W30", 1640 "48 | W32", 1642 "50 | W34", 1643 "52 | W36", 1644 "54 | W38", 1645 "56 | W40". The full group also covers W23–W54, but the UI offers W28–W40.

**Conditions** (`status_ids`): 6 Nou cu etichetă, 1 Nou fără etichetă, 2 Foarte bună, 3 Bună, 4 Satisfăcătoare. 6 and 1 are verified live. 2/3/4 are confirmed by the plan's first task before the UI offers them.

**Brands:** `/api/v2/brands?keyword=<text>` (works from inside a vinted.ro browser page, verified 2026-09-27).

## 3. Architecture

```
Browser (localhost:8000) ──htmx every 30 s──► Dashboard process            Tracker process
                                               python -m vinted_tracker      python -m vinted_tracker run
                                               dashboard                     (unchanged loop)
                                                  │ reads/writes                │ reads settings each tick
                                                  ▼                             ▼
                                               PostgreSQL: items, observations, … + watch_settings,
                                                           tracker_status, brand_cache
```

- **Two independent processes** sharing PostgreSQL. The dashboard never scrapes listings and the tracker never serves pages. Either can restart without affecting the other.
- **New package `vinted_tracker/web/`:**

| Module | Responsibility |
|---|---|
| `web/app.py` | FastAPI app factory `create_app(conn_factory, lookup)`, all routes |
| `web/templates/` | `page.html` (full page), `_status.html`, `_tiles.html`, `_products.html`, `_settings.html` fragments |
| `web/static/` | `htmx.min.js`, `chart.umd.min.js` (vendored, pinned versions), `app.css`, `charts.js` |
| `stats.py` | SQL for tiles, chart series and the product table. The Excel summaries in `export.py` reuse the same functions. |
| `watch_settings.py` | `WatchSettings` dataclass, validation, load/save to DB, seeding from `config.yaml`, conversion to tracker `Query` objects |
| `vinted_ref.py` | Static Vinted reference data from §2 plus a leaf-catalog → product-type map (generated once from the catalog tree by a script in `scripts/`) |
| `brand_lookup.py` | On-demand brand search: short-lived headless Chromium with its own profile (`browser-profile-lookup`), cached in `brand_cache` |

### 3.1 Settings storage

Table `watch_settings(id smallint PRIMARY KEY CHECK (id = 1), data jsonb NOT NULL, version integer NOT NULL, updated_at timestamptz NOT NULL)`, a single row:

```json
{
  "groups": [{"name": "streetwear", "brands": [{"id": 53, "title": "Nike"}]}],
  "catalog_ids": [257, 1206, 76, 32, 79, 34, 80, 85, 2910, 84, 30, 92, 83],
  "size_ids": [],
  "status_ids": [6, 1]
}
```

- **Seeding:** if the row doesn't exist, it is created from `config.yaml` (today's three groups and brands, all 13 types, no size filter, conditions 6 and 1). Brand titles come from the comments in `config.yaml`, typed into the seed.
- **Validation** (refused with a message, nothing saved):
  - at least one group;
  - each group has a unique, non-empty name and at least one brand;
  - at least one product type;
  - at least one condition;
  - every id is from the reference lists, except brands, which come from a lookup.
- **`version`** increments on every save.

### 3.2 Tracker changes

- `config.yaml` keeps only technical settings. Its `queries:` and `allowed_conditions` become the **seed** only; once the DB row exists, the DB wins.
- **Before each tick**, the runner reads `watch_settings.version`. When it changed, the runner rebuilds:
  - `cfg.queries`: one `Query` per group, with `catalog_ids`, `brand_ids`, `status_ids` and the new `size_ids`;
  - `cfg.allowed_conditions`, from the selected status ids.
- `build_catalog_url` adds `size_ids[]=…` (empty means no size filter).
- **The safety check** stays: conditions are checked on each listing. Sizes aren't re-checked locally, because Vinted's size label formats vary.
- `query_state` is keyed by group name. A renamed or new group starts with a baseline poll (no tracking on its first poll), as today.
- **Hourly quota** stays `ceil(max_new_per_day / 24 / number_of_groups)`.

### 3.3 Tracker status

Table `tracker_status(id smallint PRIMARY KEY CHECK (id = 1), data jsonb, updated_at timestamptz)`. `Runner.write_status()` writes the same JSON it puts in `status.json` (which is kept). The CLI `status` command reads the DB.

The dashboard derives a **state**:

| State | When |
|---|---|
| `ok` (green) | heartbeat < 10 min old and health `ok` |
| `blocked` (orange) | shows `last_error` and when the pause ends |
| `parser_broken` / `network_error` (orange) | shows the health and `last_error` |
| `stopped` (red) | heartbeat ≥ 10 min old, or no row at all |

### 3.4 Page and endpoints

| Route | Returns |
|---|---|
| `GET /` | full page |
| `GET /fragments/status` | top bar (polled every 30 s) |
| `GET /fragments/tiles` | 5 tiles: tracking, sold, deleted, median hours to sell, % sold within 7 days (polled every 30 s) |
| `GET /api/charts` | JSON: median hours to sell by brand, by product type, by size and by price band. Only buckets with at least 3 certain sales; otherwise the chart shows "not enough sold items yet". |
| `GET /fragments/products?status=&brand=&type=&q=&page=` | table rows, newest first, 50 per page, polled every 30 s |
| `GET /export.xlsx` | Excel report download, filename `vinted_report_YYYY-MM-DD.xlsx` |
| `GET /fragments/settings` | settings panel |
| `POST /settings` | validate + save. Returns the panel with "Saved, applies within ~5 min" or the error messages. |
| `GET /brands/search?q=` | brand search results (fragment) |

**Product table columns:**
- **Status pill:** Tracking / Sold / Deleted / Unsold 30 d / Hidden;
- brand; title linking to vinted.ro; product type (from `vinted_ref`); size;
- **price**, shown as `listed → lowest` when it dropped;
- listed (relative time);
- **sold after**, shown as the `min–max` range, marked "≈" when uncertain;
- favourites, last checked, next check.

Out-of-scope items (from the scope change on 2026-09-28) are excluded everywhere, as in the Excel report.

### 3.5 Brand lookup

`GET /brands/search?q=nike`:
1. Check `brand_cache(keyword text PRIMARY KEY, results jsonb, fetched_at timestamptz)`. Entries are valid for 30 days.
2. Otherwise, open a headless Chromium with profile `browser-profile-lookup`, load the vinted.ro catalog page, run `fetch('/api/v2/brands?keyword=…')` inside the page, close the browser and cache the top 10 results (id, title, item count).
3. At most one lookup at a time, at least 5 s apart. A challenge or failure returns "Vinted didn't answer, try again in a few minutes".

## 4. Error handling

| Situation | Behaviour |
|---|---|
| Database unreachable | Fragments render "Can't reach the database" and the next poll retries. The process doesn't exit. |
| Tracker heartbeat ≥ 10 min old | Red status bar: "Tracker stopped (no check for N min)". |
| Invalid settings | `POST /settings` returns the panel with field-level messages and saves nothing. |
| Brand lookup blocked / no results | Message in the search box. Settings are unaffected. |
| Not enough data for a chart | Chart area shows "not enough sold items yet (needs ≥ 3 per bar)". |
| Port 8000 in use | Startup error naming the port. A `--port` option is provided. |

## 5. Running it

- `python -m vinted_tracker dashboard [--port 8000]` starts uvicorn on `127.0.0.1:<port>`.
- Optional Windows scheduled task `VintedDashboard` (at logon, `conhost --headless`, like the tracker), registered by `scripts/register_dashboard_task.ps1` with the owner's OK.
- New dependencies: `fastapi`, `uvicorn`, `jinja2`, `python-multipart` (form posts), `httpx` (test client only, dev extra).

## 6. Testing

- **`stats.py`:** tile numbers, chart series and product-table rows against the test DB with synthetic items (the same style as `test_export.py`).
- **`watch_settings.py`:**
  - seeding from `config.yaml`, save/load round trip, version increments;
  - each validation rule;
  - conversion to `Query` objects, including `size_ids`.
- **Tracker:** the runner picks up a new settings version on the next tick without a restart; `build_catalog_url` includes `size_ids[]`.
- **Web (FastAPI `TestClient`, test DB):**
  - every route returns 200 with the expected content;
  - `POST /settings` saves valid input and refuses invalid input;
  - `/export.xlsx` is a workbook that `pandas.read_excel` opens;
  - status turns red when the heartbeat is old;
  - product filters work.
- **Brand lookup:** a cache hit makes no browser call, and a failure returns the message. Tests use a fake fetcher and never contact Vinted.
- **Manual check:** open the real dashboard, change a setting, and confirm in the tracker log that the next poll uses the new URL.

## 7. Out of scope

Login/HTTPS (done at the Hetzner step), Docker changes (next project), multiple users, editing schedule and rate settings in the UI, mobile-specific layout beyond "readable on a phone", notifications.
