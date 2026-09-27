# Vinted Sell-Time Tracker — Design

Date: 2026-09-27
Status: Draft, awaiting review

## 1. Goal

Measure how long newly listed men's clothing takes to sell on vinted.ro, so the owner can decide what to buy and resell and at what price.

**Success:** after a few weeks of running, answer questions like "a Nike hoodie, size M, 60–100 RON, from a Romanian seller sells in a median of X days (n = Y)", sliced by brand, category, size, condition and price band.

### Decisions from brainstorming

| Topic | Decision |
|---|---|
| Purpose | Reselling / flipping |
| Market | vinted.ro, prices in RON |
| Sellers | **Romanian sellers only**. vinted.ro also shows listings from other countries, and those are excluded. |
| Scope | Configurable watchlist of brands and categories within men's clothing |
| Initial watchlist | Streetwear (Nike, Adidas, The North Face, Carhartt, Stussy), premium casual (Ralph Lauren, Tommy Hilfiger, Lacoste, Hugo Boss), designer (Stone Island, CP Company, Moncler). **Designer brands have no price filter**: cheap and possibly fake listings are tracked too. |
| Listing age | Track only listings first seen within 60 minutes of upload. Older listings are ignored. |
| Language / runtime | Python + Playwright (Chromium). Runs on the owner's Windows PC first, portable to a Linux VPS via Docker later. |
| Output | Excel export now. Local dashboard as a separate, later project. |
| Captchas | **Not solved.** When challenged, the tracker backs off and alerts. No evasion or solver services. |

## 2. What the site probe found (2026-09-27)

- A real Chromium session loads vinted.ro catalog and item pages without a challenge.
- The old JSON endpoint `/api/v2/catalog/items` returns **404**. Listings are rendered on the server and embedded as JSON in the page's Next.js data (`self.__next_f` script chunks).
- Catalog URL: `https://www.vinted.ro/catalog?catalog[]=<id>&brand_ids[]=<id>&order=newest_first&page=N`. Men's clothing root is catalog `5`.
- Catalog item fields available: `id`, `title`, `url`, `price{amount,currencyCode}` (converted to RON), `totalItemPrice`, `serviceFee`, `favouriteCount`, `user.id`, and brand, condition and size in the card's accessibility label.
- Item page fields available: `can_buy`, `is_reserved`, `is_hidden`, `catalog_id`, `favourite_count`, the **seller's original price and currency** (for example `150 PLN` for a Polish seller), and upload time as text ("Încărcat acum 3 minute").
- **Not yet observed:** how a *sold*, *reserved* or *deleted* item looks in page data. The Phase 0 spike resolves this.

## 3. Architecture

A single long-running Python process with one browser session.

```
config.yaml ─► scheduler loop
                 ├─ discover  (catalog newest_first per watchlist query → new item IDs)
                 ├─ recheck   (revisit tracked items on a backoff schedule)
                 │     both use ─► browser (one Playwright Chromium, persistent profile, rate-limited)
                 │               ─► parse   (embedded JSON → typed records; ONLY module aware of Vinted page structure)
                 └─ db (SQLite: items, observations, runs)
export ─► vinted_report.xlsx
status ─► status.json (progress / health snapshot)
```

### Modules (`vinted_tracker/`)

| Module | Responsibility | Depends on |
|---|---|---|
| `config.py` | Load and validate `config.yaml` (watchlist, intervals, rate limits, caps) | — |
| `browser.py` | Own the Playwright session: persistent profile, blocks images, fonts, media and ad domains, enforces a random 8–12s gap between page loads and an hourly page cap, detects challenge pages | Playwright |
| `parse.py` | Pure functions: page HTML/script text → `CatalogItem` / `ItemSnapshot`. Raises `ParseError` on unexpected structure. | — |
| `models.py` | Dataclasses and enums (`Status`: available, reserved, sold, hidden, deleted, unknown) | — |
| `db.py` | SQLite schema, migrations, queries | sqlite3 |
| `discover.py` | Build catalog URLs from the watchlist, parse, apply the new-listing and Romanian-seller filters, insert tracked items | browser, parse, db |
| `schedule.py` | Pure: given an item's age and last check → next check time. Budget-aware stretching. | — |
| `recheck.py` | Pick due items, fetch the item page, store an observation, detect status transitions | browser, parse, db, schedule |
| `runner.py` | Main loop alternating discover and recheck, backoff on blocks, graceful shutdown, writes `status.json` | all above |
| `export.py` | SQLite → Excel (raw sheet + summary sheets) | pandas, openpyxl |
| `__main__.py` | CLI: `run`, `export`, `status`, `probe <url>` | — |

## 4. Data flow and rules

### 4.1 Discovery (every ~5 min per watchlist query)
1. Load page 1 (and page 2 if every item on page 1 was new) of the newest-first catalog for the query.
2. For each item not already known, apply these filters:
   - **New:** upload age < 60 min **and** item ID ≥ (highest seen ID − tolerance), which rejects bumped old listings.
   - **Romanian seller:** the seller's original currency is `RON`. Phase 0 checks whether this is available on the catalog page. If not, it's checked on the first item-page visit, and non-RON items are dropped at that point.
   - **Daily cap:** stop adding once `max_new_per_day` (default 250) is reached.
3. Insert the item with `first_seen_at`, `uploaded_at_estimate` and the static attributes (brand, category, size, condition, listed price, seller id, watchlist query).

### 4.2 Recheck schedule (all intervals configurable)
| Item age | Interval |
|---|---|
| < 24 h | 2 h |
| 1–7 days | 8 h |
| 7–30 days | 24 h |
| > 30 days | stop, final status `unsold_30d` |

If the due queue exceeds the page budget, intervals stretch in proportion. The rate limit never increases.

### 4.3 Status and sell time
- Each visit stores an **observation**: status, price, favourite count and timestamp.
- The final outcome is one of `sold`, `deleted`, `hidden`, `unsold_30d` (reserved is transitional).
- `sold_after_min` = last check where the item was available − upload time; `sold_after_max` = first check where it showed sold − upload time. The report shows the midpoint and the ± range.
- Items that went available → deleted, or have a gap of more than 48h between checks, are flagged `uncertain` and left out of the headline medians.

### 4.4 Database (SQLite, `data/tracker.db`)
- `items(id PK, title, brand, catalog_id, size, condition, price_listed_ron, original_price, original_currency, seller_id, query_name, uploaded_at, first_seen_at, final_status, sold_after_min_s, sold_after_max_s, uncertain, last_checked_at, next_check_at)`
- `observations(item_id, observed_at, status, price_ron, favourite_count)`
- `runs(started_at, ended_at, pages_loaded, items_discovered, items_rechecked, blocks, parse_errors)`

### 4.5 Export (`python -m vinted_tracker export`)
`vinted_report.xlsx` with these sheets:
- **Items:** one row per tracked item, including status and sell-time range.
- **By brand / By category / By size / By price band:** count sold, median and p25/p75 sell time, sell-through rate (% sold within 7 and 30 days), median price, average price drop.
- **Price drops:** items whose price changed before selling.

## 5. Error handling

| Situation | Behaviour |
|---|---|
| Captcha, access-denied page or repeated HTTP 403/429 | Stop all requests. Back off 30 min → 1h → 2h → 4h (max). Log a warning and set `status.json.health = "blocked"`. **Never solve or evade.** |
| Parse error | Save the page to `debug/<timestamp>-<item>.html`, record the observation as `unknown`, retry at the next interval. 10+ errors in an hour sets `health = "parser_broken"`. |
| Crash or PC off | State lives entirely in SQLite. On restart, overdue items are checked first. Wider gaps show up as wider sell-time ranges or `uncertain`. |
| Network failure | Retry up to 3 times with backoff, then skip until the next cycle. |

## 6. Testing

- **Parser tests** use saved sample pages in `tests/fixtures/`: a catalog page, and item pages that are available, reserved, sold and deleted (captured in Phase 0).
- **Pure logic tests:** new-listing filter, Romanian-seller filter, schedule, sell-time calculation, budget stretching. No network.
- **DB and export tests** use a temporary SQLite database and synthetic data.
- **Live smoke test** (`probe` command, run by hand): fetch one catalog page and one item page and check they parse.
- The pytest suite runs offline.

## 7. Build phases

0. **Spike** (throwaway): track about 50 new items for about 24h. Capture sold, reserved and deleted page fixtures. Confirm status fields and the cheapest Romanian-seller signal. Output: findings notes plus fixtures.
1. Project skeleton, config, models, DB.
2. Parser (against the fixtures).
3. Browser session + discovery.
4. Schedule + recheck.
5. Runner loop, backoff, `status.json`.
6. Excel export.
7. Unattended running: Windows Task Scheduler script now, Dockerfile for later.

## 8. Out of scope

Captcha solving or bot evasion, proxies, the dashboard (separate later project), non-Romanian sellers, womenswear and kids, detecting fakes, automatic buying or messaging.
