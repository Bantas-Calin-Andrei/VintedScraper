"""Vinted reference data for men's clothing on vinted.ro (probed 2026-10-04)."""
from __future__ import annotations

CLOTHING_ROOT = 2050  # Bărbați > Haine

PRODUCT_TYPES: dict[int, str] = {
    257: "Blugi",
    1206: "Îmbrăcăminte de exterior",
    76: "Topuri și tricouri",
    32: "Costume și blazere",
    79: "Pulovere",
    34: "Pantaloni",
    80: "Pantaloni scurți",
    85: "Șosete și lenjerie intimă",
    2910: "Haine de dormit",
    84: "Costume de baie",
    30: "Îmbrăcăminte pentru sport",
    92: "Costume și ținute speciale",
    83: "Alte articole de îmbrăcăminte",
}

LETTER_SIZES: dict[int, str] = {
    206: "XS", 207: "S", 208: "M", 209: "L", 210: "XL", 211: "XXL", 212: "XXXL",
    308: "4XL", 309: "5XL", 1192: "6XL", 1193: "7XL", 1194: "8XL",
}

WAIST_SIZES: dict[int, str] = {1636: "W28", 1638: "W30", 1640: "W32", 1642: "W34", 1643: "W36", 1644: "W38", 1645: "W40"}

CONDITIONS: dict[int, str] = {
    6: "Nou cu etichetă",
    1: "Nou fără etichetă",
    2: "Foarte bună",
    3: "Bună",
    4: "Satisfăcătoare",
}

SEED_BRAND_TITLES: dict[int, str] = {
    53: "Nike", 5977: "Nike Air", 14: "adidas", 194976: "adidas Originals", 2319: "The North Face",
    362: "Carhartt", 872289: "Carhartt WIP", 441: "Stüssy", 88: "Ralph Lauren", 4273: "Polo Ralph Lauren",
    94: "Tommy Hilfiger", 304: "Lacoste", 120: "Hugo Boss", 6039857: "BOSS Hugo Boss", 1707868: "HUGO Hugo Boss",
    73306: "Stone Island", 73952: "C.P. Company", 6539: "Moncler",
}

_TYPE_CATALOGS: dict[int, tuple[int, ...]] = {
    257: (257, 1816, 1817, 1818, 1819),
    1206: (1206, 1223, 1224, 1225, 1226, 1227, 1230, 1858, 1859, 1861, 2051, 2052,
           2533, 2534, 2535, 2536, 2537, 2538, 2539, 2550, 2551, 2552, 2553),
    76: (76, 77, 536, 560, 1801, 1802, 1803, 1804, 1805, 1806, 1807, 1808, 1810, 1865, 1868, 5492),
    32: (32, 1786, 1787, 1788, 1789, 1790, 1866),
    79: (79, 264, 265, 266, 267, 268, 1811, 1812, 1813, 1814, 1815, 1825),
    34: (34, 259, 260, 261, 263, 271, 1820, 1821),
    80: (80, 272, 1822, 1823, 1824),
    85: (85, 1828, 1829, 1830, 1867),
    2910: (2910, 2911, 2912, 2913, 2914),
    84: (84,),
    30: (30, 581, 582, 583, 584, 585, 586, 587, 588, 1470, 1471, 1473, 1474, 3050, 3267),
    92: (92,),
    83: (83,),
}
_TYPE_OF: dict[int, int] = {cid: type_id for type_id, cids in _TYPE_CATALOGS.items() for cid in cids}


def catalog_ids_of_type(type_id: int) -> tuple[int, ...]:
    return _TYPE_CATALOGS.get(type_id, ())


def product_type_of(catalog_id: int | None) -> str | None:
    type_id = _TYPE_OF.get(catalog_id) if catalog_id is not None else None
    return PRODUCT_TYPES.get(type_id) if type_id is not None else None
