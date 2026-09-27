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


def count_new_since(conn: psycopg.Connection, since: datetime, query_name: str | None = None) -> int:
    if query_name is None:
        sql, params = "SELECT count(*) AS n FROM items WHERE first_seen_at >= %s", (since,)
    else:
        sql = "SELECT count(*) AS n FROM items WHERE first_seen_at >= %s AND query_name = %s"
        params = (since, query_name)
    return conn.execute(sql, params).fetchone()["n"]


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
