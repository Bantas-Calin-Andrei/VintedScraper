# Docker deployment and Docker-based development — design

Date: 2026-11-01. Status: approved direction (the user skipped detailed questions; calls marked *my call* are open to change).

## Intent

Move the Vinted sell-time tracker off the user's Windows PC onto a rented Hetzner Cloud server, running 24/7 in Docker. The user also wants to change the code on their laptop **using Docker only**, with nothing installed there except Docker Desktop (no Python, PostgreSQL or Chromium on the laptop).

The Windows PC that runs the tracker today **cannot install Docker Desktop**, so all building and testing of this work happens on the laptop. The PC keeps tracking until the server takes over, and it is where the final data export is made.

## Goals

1. One `docker compose up -d` on the server starts PostgreSQL, the tracker and the dashboard, and they come back on their own after a crash or reboot.
2. The same repo runs on the laptop in a **dev mode**: dashboard on http://localhost:8000, the test suite runs inside a container, code edits on the laptop are picked up without rebuilding the image.
3. The existing data (items, observations, settings, manual requests, etc.) moves from the PC's PostgreSQL 18 to the server with no loss and no period where two trackers run at once.
4. A step-by-step guide a non-expert can follow: SSH key, creating the server, firewall, Docker install, first start, data move, updating after a code change, switching off the PC tracker.
5. The dashboard is reachable only by the user, through an SSH tunnel (`ssh -L 8000:localhost:8000 root@<server-ip>`), never on the public internet.

## Non-goals

- A dashboard login page or HTTPS (the SSH tunnel replaces them for now).
- CI/CD, automatic deploys, Kubernetes, multiple servers.
- Proxies, residential IPs, or anything that hides or rotates the server's IP. Captchas are never solved.
- Changing how the tracker scrapes (rate limits, schedule, parsing stay as they are).

## Anti-goals (would count as failure even if it "works")

- The dashboard or PostgreSQL port reachable from the internet. Note that Docker-published ports bypass `ufw`, so ports must be published on `127.0.0.1` only, and the database port not at all.
- Secrets in git: `.env` stays git-ignored; the real database password is generated on the server and never committed or printed in logs.
- The laptop dev mode silently starting a second tracker that scrapes Vinted alongside the server one.
- Tests running against the real data database (tests must use a separate test database).

## Constraints and facts the builder needs

- Python 3.13 package `vinted_tracker` (see `pyproject.toml`); 234 tests pass on Windows (`pytest`), 2 skipped. Tests read `TEST_DATABASE_URL`; the app reads `DATABASE_URL` (both from the environment or `.env`).
- Both the tracker **and the dashboard** need Playwright Chromium (the dashboard's brand search opens a browser), so both run from the same image.
- The tracker uses a persistent browser profile in `browser-profile/`, writes `logs/` and `debug/`, a `status.json` heartbeat and a `tracker.lock` single-instance lock. The dashboard reads tracker health from the database (`tracker_status`), not from `status.json`.
- `python -m vinted_tracker dashboard` currently binds uvicorn to `127.0.0.1` only; inside a container it must listen on `0.0.0.0`.
- `DATABASE_DOWN_HELP` in `vinted_tracker/__main__.py` tells the user to start the Windows service `postgresql-x64-18`, and `tests/test_cli.py` asserts that text; in Docker the advice is wrong and must become environment-neutral (or Docker-aware).
- The existing `Dockerfile`, `docker-compose.yml` and `.dockerignore` are untested drafts; replace them freely.
- PostgreSQL is version 18 on the PC; the server uses the official `postgres:18` image (its data volume mounts at `/var/lib/postgresql`).
- The server may be any Hetzner plan in stock (the user will take what is available; billed hourly). Plan for as little as 2 GB RAM: add a swap file in the guide and keep Chromium's memory sane. The server may be ARM (CAX) or x86, so the image must build on both.
- Server location: Germany or Finland. OS: Ubuntu 24.04.

## Decided (as the user decided it)

- Hosting: Hetzner Cloud, whatever plan is in stock, with a ~24 h trial to see whether Vinted blocks the datacenter IP; if blocked, fall back to a device at home.
- Docker on the server **and** on the laptop; no other installs on the laptop.
- Access to the server: SSH with a key; dashboard through an SSH tunnel.

## The design (my calls unless stated above)

### Image

- One image for tracker and dashboard: `python:3.13-slim`, `pip install .`, then `playwright install --with-deps chromium`. Pin the Playwright version so the browser build matches the library. Must build for `linux/amd64` and `linux/arm64`.
- Run with `init: true` (reaps Chromium child processes) and `shm_size: 1gb` (Chromium crashes with Docker's 64 MB default `/dev/shm`).

### Compose services (production, `docker-compose.yml`)

| Service | What | Notes |
|---|---|---|
| `db` | `postgres:18` | Named volume for data; `pg_isready` healthcheck; **no published port**; `restart: unless-stopped`. |
| `tracker` | `python -m vinted_tracker run` | `depends_on: db: condition: service_healthy`; volumes for `browser-profile`, `logs`, `debug`; `restart: unless-stopped`. |
| `dashboard` | `python -m vinted_tracker dashboard --host 0.0.0.0` | Published as `127.0.0.1:8000:8000` only; `depends_on` db healthy; `restart: unless-stopped`. |

- `.env` on the server holds `POSTGRES_PASSWORD` (long random, generated in the guide). `.env.example` documents the variables.
- `config.yaml` is mounted from the repo (read-only) so a `git pull` changes it without a rebuild; the watchlist itself already lives in the database.
- Logs: the app's rotating file log keeps working inside the `logs` volume; Docker's own log driver gets size limits (`max-size`/`max-file`) so container logs can't fill the disk.

### Code changes

- `dashboard --host` option (default stays `127.0.0.1`, so Windows use is unchanged).
- Database-down message that is correct in Docker (e.g. "check `docker compose ps` / `docker compose logs db`") as well as on Windows; update `tests/test_cli.py` accordingly.
- Nothing else in the app should need to change; if the builder finds something (paths, time zones, the lock file), fix it minimally and test it.

### Dev mode on the laptop

- A compose override, e.g. `docker-compose.dev.yml` (used as `docker compose -f docker-compose.yml -f docker-compose.dev.yml ...`, or a short wrapper script), that:
  - bind-mounts the repo into the containers so edits apply after `docker compose restart dashboard` (no image rebuild for code changes; rebuild only when `pyproject.toml` changes);
  - publishes the dashboard on `localhost:8000`;
  - creates a second database `vinted_test` in the same Postgres container (init script) and runs the test suite in a container against it, e.g. `docker compose ... run --rm test` → `pytest`;
  - **does not start the tracker by default** (put it behind a compose profile, e.g. `--profile tracker`), so the laptop never scrapes alongside the server unless the user asks for a short try.
- The laptop database can be filled with a copy of the real data from the same dump file used for the server move, so the dashboard has something to show.
- Short cheat-sheet of the dev commands in the README (start, stop, tests, logs, rebuild, open a shell).

### Data move (PC → server, and PC → laptop for dev)

- A PowerShell script for the **Windows PC** (`scripts/export_db.ps1`): uses the local PostgreSQL 18 `pg_dump` (`C:\Program Files\PostgreSQL\18\bin\pg_dump.exe`) to write a custom-format dump (`-Fc`) of `vinted_tracker`. It reads the connection from `.env` and does not echo the password.
- Restore steps/script on the server (and laptop): copy the dump with `scp`, then `pg_restore --no-owner --role=vinted` into the empty `db` container **before** the tracker first starts. Then `init-db` must still be safe (schema is `CREATE ... IF NOT EXISTS` / `ALTER ... IF NOT EXISTS`).
- Switchover order (in the guide): (1) server set up and dashboard verified with a test restore; (2) on the PC stop the tracker (`scripts\stop_tracker.ps1`) and disable the `VintedTracker` task; (3) export again from the PC; (4) restore on the server over the test data; (5) start the tracker on the server; (6) watch the dashboard status for a day. If the server is blocked by Vinted, re-enable the PC task (the PC's data is from the switchover moment; anything gathered on the server in between is exported back the same way).

### Backups on the server

- A daily `pg_dump` of the database to a dated file on the server, keeping the last 7 (cron on the host calling `docker compose exec -T db pg_dump ...`). Mention Hetzner's paid snapshot/backup option as an extra.

### Updating the server after a change

- From the laptop: commit and `git push`. On the server: `git pull && docker compose up -d --build`. Wrap it in `scripts/update.sh`.
- The server gets the repo with `git clone`; if the GitHub repo is private, the guide sets up a read-only deploy key.

### The deployment guide

`docs/deploy.md`, written for the user (comfortable with a terminal, new to Linux servers):

1. Make an SSH key on the laptop (`ssh-keygen -t ed25519`).
2. Create the Hetzner server (Ubuntu 24.04, SSH key, any in-stock plan with ≥ 2 GB RAM, location Germany/Finland) and a Hetzner Cloud Firewall allowing only inbound TCP 22.
3. First login, system updates, automatic security updates (`unattended-upgrades`), swap file.
4. Install Docker Engine from Docker's official repository.
5. Clone the repo, create `.env` with a generated password.
6. Data restore, first start, check with `docker compose ps` and logs.
7. Open the dashboard through the SSH tunnel.
8. Switchover from the PC (order above), daily backups, updating, and how to delete the server if the trial fails.

## Left to the builder

- Exact file names of the dev override and scripts, Playwright pin, how the test database is created, whether `status.json`/`tracker.lock` live in a volume or the container filesystem.
- Whether the dev dashboard uses uvicorn auto-reload or a restart.

## Done when

- On the laptop: `docker compose` dev mode starts, the dashboard shows restored data at localhost:8000, and the full test suite passes inside the container.
- The production compose file starts all three services on a clean machine, the tracker connects to the database, scrapes, and writes a heartbeat the dashboard shows.
- `docs/deploy.md` exists and the README points to it.

## Current state at hand-off (2026-11-01)

- All app code is on `main` and pushed to GitHub (`Bantas-Calin-Andrei/VintedScraper`).
- The tracker runs on the Windows PC as the scheduled task `VintedTracker`; the PC's local PostgreSQL 18 (`postgresql-x64-18`) holds the only copy of the real data (~600 items).
- Earlier specs/plans: `2026-09-27-vinted-sell-time-tracker-design.md`, `2026-10-05-dashboard-design.md` (and plans in `docs/superpowers/plans/`).
- Next step: write the implementation plan from this design (superpowers:writing-plans), on the laptop.
