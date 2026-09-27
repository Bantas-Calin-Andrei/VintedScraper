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
