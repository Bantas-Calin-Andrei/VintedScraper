"""THROWAWAY helper: turn one spike snapshot into a test fixture.

Usage: .venv\\Scripts\\python spike\\make_fixture.py spike/out/<snapshot-base> <fixture-name>
(<snapshot-base> is the file name without .html, e.g. spike/out/10151209174-20260928T101500)
"""
import gzip
import shutil
import sys
from pathlib import Path

src, name = sys.argv[1], sys.argv[2]
dst = Path("tests/fixtures")
dst.mkdir(parents=True, exist_ok=True)
(dst / f"{name}.html.gz").write_bytes(gzip.compress(Path(f"{src}.html").read_bytes()))
shutil.copyfile(f"{src}.txt", dst / f"{name}.txt")
shutil.copyfile(f"{src}.meta.json", dst / f"{name}.meta.json")
print("wrote fixture", name)
