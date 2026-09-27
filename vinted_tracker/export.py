"""Excel report: one row per item plus sell-time summaries per brand, category, size, condition and price band."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import psycopg

PRICE_BAND_SQL = """CASE
    WHEN i.price_listed_ron IS NULL THEN '(none)'
    WHEN i.price_listed_ron < 50 THEN '0-49 RON'
    WHEN i.price_listed_ron < 100 THEN '50-99 RON'
    WHEN i.price_listed_ron < 200 THEN '100-199 RON'
    WHEN i.price_listed_ron < 400 THEN '200-399 RON'
    ELSE '400+ RON' END"""

DIMENSIONS = {
    "By brand": ("coalesce(i.brand, '(none)')", "brand"),
    "By category": ("coalesce(i.catalog_id::text, '(none)')", "catalog_id"),
    "By size": ("coalesce(i.size, '(none)')", "size"),
    "By condition": ("coalesce(i.condition, '(none)')", "condition"),
    "By price band": (PRICE_BAND_SQL, "price_band"),
}

ITEMS_SQL = """
SELECT i.id, i.title, i.brand, i.catalog_id, i.size, i.condition,
       i.price_listed_ron::float8 AS price_listed_ron,
       lp.lowest_price_ron,
       (i.uploaded_at AT TIME ZONE 'Europe/Bucharest') AS uploaded_at,
       coalesce(i.final_status, 'tracking') AS status,
       round((extract(epoch FROM i.sold_after_min) / 3600)::numeric, 1)::float8 AS sold_after_min_h,
       round((extract(epoch FROM i.sold_after_max) / 3600)::numeric, 1)::float8 AS sold_after_max_h,
       round((extract(epoch FROM (i.sold_after_min + i.sold_after_max) / 2) / 3600)::numeric, 1)::float8
           AS sold_after_h,
       i.uncertain, i.query_name,
       %(base)s || i.url AS link
FROM items i
LEFT JOIN LATERAL (
    SELECT min(o.price_ron)::float8 AS lowest_price_ron FROM observations o WHERE o.item_id = i.id
) lp ON true
ORDER BY i.uploaded_at DESC
"""

SUMMARY_SQL = """
WITH base AS (
    SELECT {expr} AS grp,
           i.final_status, i.uncertain, i.price_listed_ron,
           (extract(epoch FROM (i.sold_after_min + i.sold_after_max) / 2) / 3600)::float8 AS sold_h,
           now() - i.uploaded_at AS age,
           (SELECT min(o.price_ron) FROM observations o WHERE o.item_id = i.id) AS lowest_price
    FROM items i
)
SELECT grp AS "{label}",
       count(*) AS tracked,
       count(*) FILTER (WHERE final_status = 'sold') AS sold,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY sold_h)
              FILTER (WHERE final_status = 'sold' AND NOT uncertain))::numeric, 1)::float8 AS median_hours_to_sell,
       round((percentile_cont(0.25) WITHIN GROUP (ORDER BY sold_h)
              FILTER (WHERE final_status = 'sold' AND NOT uncertain))::numeric, 1)::float8 AS p25_hours,
       round((percentile_cont(0.75) WITHIN GROUP (ORDER BY sold_h)
              FILTER (WHERE final_status = 'sold' AND NOT uncertain))::numeric, 1)::float8 AS p75_hours,
       round(100.0 * count(*) FILTER (WHERE final_status = 'sold' AND sold_h <= 168 AND age >= interval '7 days')
             / NULLIF(count(*) FILTER (WHERE age >= interval '7 days'), 0), 1)::float8 AS pct_sold_within_7d,
       round(100.0 * count(*) FILTER (WHERE final_status = 'sold' AND sold_h <= 720 AND age >= interval '30 days')
             / NULLIF(count(*) FILTER (WHERE age >= interval '30 days'), 0), 1)::float8 AS pct_sold_within_30d,
       round((percentile_cont(0.5) WITHIN GROUP (ORDER BY price_listed_ron::float8))::numeric, 2)::float8
           AS median_price_ron,
       round(avg(100.0 * (price_listed_ron - lowest_price) / NULLIF(price_listed_ron, 0))
             FILTER (WHERE final_status = 'sold'), 1)::float8 AS avg_price_drop_pct_sold
FROM base
GROUP BY grp
ORDER BY tracked DESC, grp
"""

PRICE_DROPS_SQL = """
SELECT i.id, i.title, i.brand,
       i.price_listed_ron::float8 AS listed_ron,
       min(o.price_ron)::float8 AS lowest_ron,
       round(100.0 * (i.price_listed_ron - min(o.price_ron)) / NULLIF(i.price_listed_ron, 0), 1)::float8 AS drop_pct,
       coalesce(i.final_status, 'tracking') AS status
FROM items i
JOIN observations o ON o.item_id = i.id
GROUP BY i.id
HAVING min(o.price_ron) < i.price_listed_ron
ORDER BY drop_pct DESC
"""


def build_report(conn: psycopg.Connection, base_url: str) -> dict[str, pd.DataFrame]:
    frames = {"Items": _frame(conn, ITEMS_SQL, {"base": base_url})}
    for sheet, (expr, label) in DIMENSIONS.items():
        frames[sheet] = _frame(conn, SUMMARY_SQL.format(expr=expr, label=label))
    frames["Price drops"] = _frame(conn, PRICE_DROPS_SQL)
    return frames


def write_report(frames: dict[str, pd.DataFrame], path: Path) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for sheet, frame in frames.items():
            frame.to_excel(writer, sheet_name=sheet[:31], index=False)
        for worksheet in writer.book.worksheets:
            for column in worksheet.columns:
                width = max((len(str(cell.value)) for cell in column if cell.value is not None), default=8)
                worksheet.column_dimensions[column[0].column_letter].width = min(60, width + 2)


def _frame(conn: psycopg.Connection, sql: str, params: dict | None = None) -> pd.DataFrame:
    cur = conn.execute(sql, params)
    columns = [d.name for d in cur.description]
    return pd.DataFrame(cur.fetchall(), columns=columns)
