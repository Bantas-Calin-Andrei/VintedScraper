"""Load and validate config.yaml plus DATABASE_URL from the environment."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import yaml


class ConfigError(ValueError):
    """The configuration is missing or invalid."""


@dataclass(frozen=True)
class Query:
    name: str
    catalog_ids: tuple[int, ...]
    brand_ids: tuple[int, ...]
    price_from: float | None = None
    price_to: float | None = None


@dataclass(frozen=True)
class Config:
    base_url: str
    queries: tuple[Query, ...]
    poll_minutes: float
    max_item_age_minutes: float
    max_new_per_day: int
    whole_price_prefilter: bool
    recheck_schedule: tuple[tuple[float, float], ...]  # (max_age_hours, interval_hours), ascending
    uncertain_gap_hours: float
    min_delay_s: float
    max_delay_s: float
    max_pages_per_hour: int
    backoff_minutes: tuple[float, ...]
    headless: bool
    database_url: str


def load_config(path: str | Path, env: Mapping[str, str] | None = None) -> Config:
    env = os.environ if env is None else env
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path}") from exc
    database_url = env.get("DATABASE_URL", "")
    if not database_url:
        raise ConfigError("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
    try:
        discovery, recheck, rate = data["discovery"], data["recheck"], data["rate"]
        cfg = Config(
            base_url=str(data.get("base_url", "https://www.vinted.ro")).rstrip("/"),
            queries=tuple(_query(q) for q in data["queries"]),
            poll_minutes=float(discovery["poll_minutes"]),
            max_item_age_minutes=float(discovery["max_item_age_minutes"]),
            max_new_per_day=int(discovery["max_new_per_day"]),
            whole_price_prefilter=bool(discovery.get("whole_price_prefilter", True)),
            recheck_schedule=tuple((float(age), float(every)) for age, every in recheck["schedule"]),
            uncertain_gap_hours=float(recheck["uncertain_gap_hours"]),
            min_delay_s=float(rate["min_delay_s"]),
            max_delay_s=float(rate["max_delay_s"]),
            max_pages_per_hour=int(rate["max_pages_per_hour"]),
            backoff_minutes=tuple(float(m) for m in data["backoff_minutes"]),
            headless=bool(data.get("headless", True)),
            database_url=database_url,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigError(f"Invalid config {path}: {exc!r}") from exc
    _validate(cfg)
    return cfg


def _query(raw: dict[str, Any]) -> Query:
    return Query(
        name=str(raw["name"]),
        catalog_ids=tuple(int(x) for x in raw.get("catalog_ids") or ()),
        brand_ids=tuple(int(x) for x in raw.get("brand_ids") or ()),
        price_from=_optional_float(raw.get("price_from")),
        price_to=_optional_float(raw.get("price_to")),
    )


def _optional_float(value: Any) -> float | None:
    return None if value is None else float(value)


def _validate(cfg: Config) -> None:
    if not cfg.queries:
        raise ConfigError("At least one query is required.")
    names = [q.name for q in cfg.queries]
    if len(set(names)) != len(names):
        raise ConfigError("Query names must be unique.")
    for q in cfg.queries:
        if not q.catalog_ids and not q.brand_ids:
            raise ConfigError(f"Query {q.name!r} needs catalog_ids or brand_ids.")
        if q.price_from is not None and q.price_to is not None and q.price_from > q.price_to:
            raise ConfigError(f"Query {q.name!r}: price_from is above price_to.")
    if not 0 < cfg.min_delay_s <= cfg.max_delay_s:
        raise ConfigError("rate: need 0 < min_delay_s <= max_delay_s.")
    if cfg.max_pages_per_hour <= 0:
        raise ConfigError("rate: max_pages_per_hour must be positive.")
    ages = [age for age, _ in cfg.recheck_schedule]
    if not ages or ages != sorted(ages) or any(every <= 0 for _, every in cfg.recheck_schedule):
        raise ConfigError("recheck.schedule must be non-empty, ascending by age, with positive intervals.")
    if not cfg.backoff_minutes or any(m <= 0 for m in cfg.backoff_minutes):
        raise ConfigError("backoff_minutes must be a non-empty list of positive numbers.")
