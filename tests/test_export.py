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
