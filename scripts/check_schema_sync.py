#!/usr/bin/env python3
"""Fail if SQLite schema copies drift from analysis.graph_importer.SCHEMA_DDL."""
from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.graph_importer import SCHEMA_DDL  # noqa: E402
from query_system.query_engine import SQLITE_SCHEMA  # noqa: E402


def _read_readme_schema() -> str:
    text = (ROOT / "README.md").read_text(encoding="utf-8")
    match = re.search(r"^## SQLite Schema\s+```sql\n(.*?)\n```", text, re.MULTILINE | re.DOTALL)
    if not match:
        raise AssertionError("README.md SQLite Schema sql block not found")
    return match.group(1)


def _read_endpoint_schema() -> str:
    from query_system.app import create_app

    app = create_app()
    client = app.test_client()
    resp = client.get("/api/schema")
    if resp.status_code == 404:
        return SCHEMA_DDL
    if resp.status_code != 200:
        raise AssertionError(f"/api/schema returned HTTP {resp.status_code}")
    return resp.get_data(as_text=True)


def _assert_equal(name: str, actual: str) -> None:
    if actual != SCHEMA_DDL:
        raise AssertionError(f"{name} does not match analysis.graph_importer.SCHEMA_DDL")


def main() -> int:
    checks = {
        "README.md SQLite Schema block": _read_readme_schema(),
        "query_system.query_engine.SQLITE_SCHEMA": SQLITE_SCHEMA,
        "/api/schema": _read_endpoint_schema(),
    }
    for name, actual in checks.items():
        _assert_equal(name, actual)

    print("schema sync OK")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"schema sync FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
