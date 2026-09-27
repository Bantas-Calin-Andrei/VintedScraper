import os
import subprocess
import sys

import pytest
from helpers import load_fixture

from vinted_tracker.__main__ import build_parser, save_fixture
from vinted_tracker.models import FetchedPage


def test_parser_requires_a_command():
    with pytest.raises(SystemExit):
        build_parser().parse_args([])


def test_parser_reads_run_options():
    args = build_parser().parse_args(["--config", "x.yaml", "run", "--headed", "--max-ticks", "3"])
    assert (args.config, args.cmd, args.headed, args.max_ticks) == ("x.yaml", "run", True, 3)


def test_save_fixture_roundtrip(tmp_path):
    page = FetchedPage(url="https://www.vinted.ro/items/1-x", status=200, html="<html>ă</html>", text="Încărcat acum 3 minute")
    save_fixture(page, "sample", tmp_path)
    assert load_fixture("sample", tmp_path) == page


def test_console_output_survives_romanian_text():
    """Windows consoles and pipes default to cp1252, which cannot encode ă/ș/ț."""
    env = {k: v for k, v in os.environ.items() if k != "PYTHONIOENCODING"}
    env["PYTHONUTF8"] = "0"
    code = "from vinted_tracker.__main__ import utf8_console; utf8_console(); print('Mărime: ă ș ț')"
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, env=env)
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert "Mărime" in result.stdout.decode("utf-8")
