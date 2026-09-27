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
