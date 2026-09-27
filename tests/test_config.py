import textwrap
from pathlib import Path

import pytest

from vinted_tracker.config import ConfigError, load_config

VALID = textwrap.dedent(
    """
    base_url: https://www.vinted.ro/
    headless: true
    queries:
      - name: streetwear
        catalog_ids: [5]
        brand_ids: [53, 14]
      - name: designer
        catalog_ids: [5]
        brand_ids: [73306]
        price_from: null
        price_to: null
    discovery:
      poll_minutes: 5
      max_item_age_minutes: 60
      max_new_per_day: 250
      whole_price_prefilter: true
    recheck:
      schedule: [[24, 2], [168, 8], [720, 24]]
      uncertain_gap_hours: 48
    rate:
      min_delay_s: 8
      max_delay_s: 12
      max_pages_per_hour: 360
    backoff_minutes: [30, 60, 120, 240]
    """
)
ENV = {"DATABASE_URL": "postgresql://u:p@localhost/db"}


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "config.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_valid_config(tmp_path):
    cfg = load_config(write(tmp_path, VALID), ENV)
    assert cfg.base_url == "https://www.vinted.ro"
    assert [q.name for q in cfg.queries] == ["streetwear", "designer"]
    assert cfg.queries[0].brand_ids == (53, 14)
    assert cfg.queries[1].price_from is None
    assert cfg.recheck_schedule == ((24.0, 2.0), (168.0, 8.0), (720.0, 24.0))
    assert cfg.whole_price_prefilter is True
    assert cfg.backoff_minutes == (30.0, 60.0, 120.0, 240.0)
    assert cfg.database_url == ENV["DATABASE_URL"]


def test_missing_database_url(tmp_path):
    with pytest.raises(ConfigError, match="DATABASE_URL"):
        load_config(write(tmp_path, VALID), {})


def test_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "nope.yaml", ENV)


def test_query_needs_ids(tmp_path):
    bad = VALID.replace("    catalog_ids: [5]\n    brand_ids: [53, 14]", "    catalog_ids: []")
    with pytest.raises(ConfigError, match="catalog_ids or brand_ids"):
        load_config(write(tmp_path, bad), ENV)


def test_schedule_must_ascend(tmp_path):
    bad = VALID.replace("[[24, 2], [168, 8], [720, 24]]", "[[168, 8], [24, 2]]")
    with pytest.raises(ConfigError, match="schedule"):
        load_config(write(tmp_path, bad), ENV)


def test_min_delay_not_above_max(tmp_path):
    bad = VALID.replace("min_delay_s: 8", "min_delay_s: 20")
    with pytest.raises(ConfigError, match="min_delay_s"):
        load_config(write(tmp_path, bad), ENV)


def test_duplicate_query_names(tmp_path):
    bad = VALID.replace("name: designer", "name: streetwear")
    with pytest.raises(ConfigError, match="unique"):
        load_config(write(tmp_path, bad), ENV)


def test_project_config_is_valid():
    cfg = load_config(Path(__file__).resolve().parents[1] / "config.yaml", ENV)
    assert {q.name for q in cfg.queries} == {"streetwear", "premium_casual", "designer"}
    assert all(q.brand_ids for q in cfg.queries)
