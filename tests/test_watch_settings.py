from datetime import datetime, timezone

import pytest
from helpers import make_config, make_settings

from vinted_tracker.config import Query
from vinted_tracker.vinted_ref import PRODUCT_TYPES
from vinted_tracker.watch_settings import (
    Brand, Group, SettingsError, WatchSettings, ensure_seeded, from_form, load, save, seed_from_config, validate,
)

T0 = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)


def errors_of(settings):
    with pytest.raises(SettingsError) as info:
        validate(settings)
    return info.value.errors


def test_seed_from_config_keeps_todays_watchlist():
    cfg = make_config(queries=(Query("streetwear", (2050,), (53, 14), status_ids=(6, 1)),))
    s = seed_from_config(cfg)
    assert s.groups == (Group("streetwear", (Brand(53, "Nike"), Brand(14, "adidas"))),)
    assert s.catalog_ids == tuple(PRODUCT_TYPES)
    assert s.size_ids == ()
    assert s.status_ids == (6, 1)


def test_valid_settings_pass():
    validate(make_settings())


def test_empty_sizes_are_valid():
    validate(make_settings(size_ids=()))


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"groups": ()}, "Add at least one brand group."),
        ({"groups": (Group("  ", (Brand(53, "Nike"),)),)}, "Every group needs a name."),
        ({"groups": (Group("A", (Brand(53, "Nike"),)), Group("a", (Brand(14, "adidas"),)))}, "Two groups are called 'a'."),
        ({"groups": (Group("empty", ()),)}, "Group 'empty' needs at least one brand."),
        ({"catalog_ids": ()}, "Pick at least one product type."),
        ({"catalog_ids": (9999,)}, "Unknown product type 9999."),
        ({"size_ids": (1,)}, "Unknown size 1."),
        ({"status_ids": ()}, "Pick at least one condition."),
        ({"status_ids": (7,)}, "Unknown condition 7."),
    ],
)
def test_validation_rules(change, message):
    assert message in errors_of(make_settings(**change))


def test_queries_and_allowed_conditions():
    s = make_settings(size_ids=(208,), status_ids=(6,))
    assert s.queries() == (Query("streetwear", (76, 79), (53,), status_ids=(6,), size_ids=(208,)),)
    assert s.allowed_conditions() == ("Nou cu etichetă",)


def test_json_round_trip():
    s = make_settings(size_ids=(208, 1640))
    assert WatchSettings.from_json(s.to_json()) == s


def test_save_load_and_versions(conn):
    assert load(conn) is None
    assert save(conn, make_settings(), T0) == 1
    assert save(conn, make_settings(catalog_ids=(257,)), T0) == 2
    version, s = load(conn)
    assert version == 2 and s.catalog_ids == (257,)


def test_save_refuses_invalid_settings(conn):
    with pytest.raises(SettingsError):
        save(conn, make_settings(catalog_ids=()), T0)
    assert load(conn) is None


def test_ensure_seeded_only_seeds_once(conn):
    cfg = make_config(queries=(Query("streetwear", (2050,), (53,), status_ids=(6, 1)),))
    version, _ = ensure_seeded(conn, cfg, T0)
    save(conn, make_settings(catalog_ids=(257,)), T0)
    again, s = ensure_seeded(conn, cfg, T0)
    assert (version, again) == (1, 2)
    assert s.catalog_ids == (257,)


def test_from_form_reads_groups_by_key_and_dedupes_brands():
    items = [
        ("group_key", "g0"), ("group_name_g0", " Streetwear "),
        ("brand_g0", "53|Nike"), ("brand_g0", "53|Nike"), ("brand_g0", "14|adidas"),
        ("group_key", "n17"), ("group_name_n17", "Designer"), ("brand_n17", "6539|Moncler"),
        ("brand_g9", "1|orphan of a removed group"),
        ("catalog_ids", "76"), ("catalog_ids", "79"), ("size_ids", "208"), ("status_ids", "6"),
        ("brand_q", "ignored search text"),
    ]
    s = from_form(items)
    assert s.groups == (
        Group("Streetwear", (Brand(53, "Nike"), Brand(14, "adidas"))),
        Group("Designer", (Brand(6539, "Moncler"),)),
    )
    assert (s.catalog_ids, s.size_ids, s.status_ids) == ((76, 79), (208,), (6,))


def test_from_form_rejects_garbage():
    with pytest.raises(SettingsError):
        from_form([("group_key", "g0"), ("group_name_g0", "x"), ("brand_g0", "abc|Nike")])


def test_price_range_goes_into_every_query():
    s = make_settings(price_from=100.0, price_to=None)
    assert s.queries()[0].price_from == 100.0 and s.queries()[0].price_to is None
    assert WatchSettings.from_json(s.to_json()) == s


def test_old_settings_rows_without_prices_still_load():
    data = make_settings().to_json()
    del data["price_from"], data["price_to"]
    assert WatchSettings.from_json(data).price_from is None


@pytest.mark.parametrize(
    ("prices", "message"),
    [((-5.0, None), "Prices can't be negative."), ((300.0, 100.0), "Min price is higher than max price.")],
)
def test_price_validation(prices, message):
    assert message in errors_of(make_settings(price_from=prices[0], price_to=prices[1]))


def test_from_form_reads_prices():
    base = [("group_key", "g0"), ("group_name_g0", "x"), ("brand_g0", "53|Nike"), ("catalog_ids", "76"), ("status_ids", "6")]
    s = from_form(base + [("price_from", "100"), ("price_to", " ")])
    assert (s.price_from, s.price_to) == (100.0, None)
    assert from_form(base + [("price_from", "99,5")]).price_from == 99.5
    with pytest.raises(SettingsError):
        from_form(base + [("price_from", "cheap")])
