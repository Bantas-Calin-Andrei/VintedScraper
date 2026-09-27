"""THROWAWAY: is 'catalog price has decimals => foreign seller' safe?"""
import json
from pathlib import Path

from vinted_tracker.parse import parse_catalog

catalog = {i.id: i for i in parse_catalog(Path("spike/out/catalog.html").read_text(encoding="utf-8"))}
first: dict[int, dict] = {}
for line in Path("spike/out/changes.jsonl").read_text(encoding="utf-8").splitlines():
    row = json.loads(line)
    first.setdefault(row["id"], row)


def has_decimals(item_id: int) -> bool:
    price = catalog[item_id].price_ron
    return price is not None and price != price.to_integral_value()


ron = [i for i, r in first.items() if r.get("currency") == "RON" and i in catalog]
foreign = [i for i, r in first.items() if r.get("currency") not in (None, "RON") and i in catalog]
print(f"items={len(first)} RON={len(ron)} foreign={len(foreign)}")
print(f"RON sellers WITH decimals (would be wrongly skipped): {sum(has_decimals(i) for i in ron)}")
print(f"foreign sellers WITHOUT decimals (would still cost a page visit): {sum(not has_decimals(i) for i in foreign)}")
