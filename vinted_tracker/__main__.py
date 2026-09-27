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


def utf8_console() -> None:
    """Windows consoles and pipes default to cp1252, which cannot print Romanian listing text."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


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
    utf8_console()
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
