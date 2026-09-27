import os
from pathlib import Path

import pytest
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]


def _test_database_url() -> str | None:
    return os.environ.get("TEST_DATABASE_URL") or dotenv_values(ROOT / ".env").get("TEST_DATABASE_URL")


@pytest.fixture
def conn():
    from vinted_tracker import db

    url = _test_database_url()
    if not url:
        pytest.skip("TEST_DATABASE_URL not set (see .env.example)")
    connection = db.connect(url)
    db.init_schema(connection)
    connection.execute("TRUNCATE items, observations, skipped_items, query_state, runs RESTART IDENTITY CASCADE")
    yield connection
    connection.close()
