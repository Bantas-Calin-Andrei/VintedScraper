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
