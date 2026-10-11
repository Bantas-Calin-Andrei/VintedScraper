from vinted_tracker.vinted_ref import (
    CONDITIONS, LETTER_SIZES, PRODUCT_TYPES, SEED_BRAND_TITLES, WAIST_SIZES, catalog_ids_of_type, product_type_of,
)


def test_product_type_of_maps_sub_categories_to_their_type():
    assert product_type_of(1803) == "Topuri și tricouri"
    assert product_type_of(2536) == "Îmbrăcăminte de exterior"
    assert product_type_of(257) == "Blugi"
    assert product_type_of(1812) == "Pulovere"


def test_product_type_of_unknown_is_none():
    assert product_type_of(None) is None
    assert product_type_of(1242) is None  # sneakers: not clothing


def test_every_type_has_its_sub_categories():
    all_ids = [cid for type_id in PRODUCT_TYPES for cid in catalog_ids_of_type(type_id)]
    assert len(all_ids) == len(set(all_ids)) == 104
    assert all(type_id in catalog_ids_of_type(type_id) for type_id in PRODUCT_TYPES)
    assert 1812 in catalog_ids_of_type(79)


def test_reference_lists():
    assert len(PRODUCT_TYPES) == 13
    assert CONDITIONS == {6: "Nou cu etichetă", 1: "Nou fără etichetă", 2: "Foarte bună", 3: "Bună", 4: "Satisfăcătoare"}
    assert LETTER_SIZES[208] == "M" and WAIST_SIZES[1640] == "W32"
    assert SEED_BRAND_TITLES[53] == "Nike" and len(SEED_BRAND_TITLES) == 18
