"""What the tracker follows (brand groups, product types, sizes, conditions).

Stored in the `watch_settings` table, edited in the dashboard, re-read by the tracker every loop tick.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import psycopg

from . import db
from .config import Config, Query
from .vinted_ref import CONDITIONS, LETTER_SIZES, PRODUCT_TYPES, SEED_BRAND_TITLES, WAIST_SIZES


class SettingsError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


@dataclass(frozen=True)
class Brand:
    id: int
    title: str


@dataclass(frozen=True)
class Group:
    name: str
    brands: tuple[Brand, ...]


@dataclass(frozen=True)
class WatchSettings:
    groups: tuple[Group, ...]
    catalog_ids: tuple[int, ...]
    size_ids: tuple[int, ...]
    status_ids: tuple[int, ...]

    def queries(self) -> tuple[Query, ...]:
        return tuple(
            Query(
                name=g.name,
                catalog_ids=self.catalog_ids,
                brand_ids=tuple(b.id for b in g.brands),
                status_ids=self.status_ids,
                size_ids=self.size_ids,
            )
            for g in self.groups
        )

    def allowed_conditions(self) -> tuple[str, ...]:
        return tuple(CONDITIONS[s] for s in self.status_ids if s in CONDITIONS)

    def to_json(self) -> dict:
        return {
            "groups": [{"name": g.name, "brands": [{"id": b.id, "title": b.title} for b in g.brands]} for g in self.groups],
            "catalog_ids": list(self.catalog_ids),
            "size_ids": list(self.size_ids),
            "status_ids": list(self.status_ids),
        }

    @classmethod
    def from_json(cls, data: dict) -> "WatchSettings":
        return cls(
            groups=tuple(
                Group(str(g["name"]), tuple(Brand(int(b["id"]), str(b["title"])) for b in g["brands"]))
                for g in data["groups"]
            ),
            catalog_ids=tuple(int(x) for x in data["catalog_ids"]),
            size_ids=tuple(int(x) for x in data["size_ids"]),
            status_ids=tuple(int(x) for x in data["status_ids"]),
        )


def validate(s: WatchSettings) -> None:
    errors: list[str] = []
    if not s.groups:
        errors.append("Add at least one brand group.")
    seen: set[str] = set()
    for g in s.groups:
        name = g.name.strip()
        if not name:
            errors.append("Every group needs a name.")
            continue
        if name.casefold() in seen:
            errors.append(f"Two groups are called '{name}'.")
        seen.add(name.casefold())
        if not g.brands:
            errors.append(f"Group '{name}' needs at least one brand.")
    if not s.catalog_ids:
        errors.append("Pick at least one product type.")
    errors += [f"Unknown product type {c}." for c in s.catalog_ids if c not in PRODUCT_TYPES]
    errors += [f"Unknown size {z}." for z in s.size_ids if z not in LETTER_SIZES and z not in WAIST_SIZES]
    if not s.status_ids:
        errors.append("Pick at least one condition.")
    errors += [f"Unknown condition {c}." for c in s.status_ids if c not in CONDITIONS]
    if errors:
        raise SettingsError(errors)


def seed_from_config(cfg: Config) -> WatchSettings:
    """Today's config.yaml watchlist: all its groups and brands, every clothing type, no size filter."""
    groups = tuple(
        Group(q.name, tuple(Brand(b, SEED_BRAND_TITLES.get(b, f"Brand {b}")) for b in q.brand_ids)) for q in cfg.queries
    )
    first = cfg.queries[0] if cfg.queries else None
    status_ids = first.status_ids if first and first.status_ids else tuple(
        s for s, name in CONDITIONS.items() if name in cfg.allowed_conditions
    ) or (6, 1)
    return WatchSettings(
        groups=groups,
        catalog_ids=tuple(PRODUCT_TYPES),
        size_ids=first.size_ids if first else (),
        status_ids=status_ids,
    )


def load(conn: psycopg.Connection) -> tuple[int, WatchSettings] | None:
    row = db.get_watch_settings(conn)
    return None if row is None else (row[0], WatchSettings.from_json(row[1]))


def save(conn: psycopg.Connection, s: WatchSettings, now: datetime) -> int:
    validate(s)
    return db.save_watch_settings(conn, s.to_json(), now)


def ensure_seeded(conn: psycopg.Connection, cfg: Config, now: datetime) -> tuple[int, WatchSettings]:
    loaded = load(conn)
    if loaded is not None:
        return loaded
    seed = seed_from_config(cfg)
    return save(conn, seed, now), seed


def from_form(items: list[tuple[str, str]]) -> WatchSettings:
    """Build settings from the panel's form fields. Groups are keyed so removed groups leave no gaps."""
    def first(key: str) -> str:
        return next((v for k, v in items if k == key), "")

    def ints(key: str) -> tuple[int, ...]:
        return tuple(dict.fromkeys(int(v) for k, v in items if k == key))

    try:
        groups = []
        for key in dict.fromkeys(v for k, v in items if k == "group_key"):
            brands: dict[int, Brand] = {}
            for k, v in items:
                if k == f"brand_{key}":
                    brand_id, _, title = v.partition("|")
                    brands.setdefault(int(brand_id), Brand(int(brand_id), title.strip()))
            groups.append(Group(first(f"group_name_{key}").strip(), tuple(brands.values())))
        return WatchSettings(tuple(groups), ints("catalog_ids"), ints("size_ids"), ints("status_ids"))
    except ValueError as exc:
        raise SettingsError(["The form contained invalid data. Reload the panel and try again."]) from exc
