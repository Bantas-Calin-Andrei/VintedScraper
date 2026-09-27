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
