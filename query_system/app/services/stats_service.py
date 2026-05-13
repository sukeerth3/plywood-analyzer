"""Stats aggregator with TTL caching.

Merges Neo4j counts with SQLite rollups; backend status flags identify
unreachable services so the Overview tab can avoid fabricated counts.
"""
from __future__ import annotations

import logging
import re
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from .engine_pool import EnginePool

log = logging.getLogger("plywood.stats")


@dataclass(frozen=True)
class Stats:
    functions: int
    graph_edges: int
    graph_nodes: int
    coverage_pct: float
    warnings: int | None
    scan_bugs: int | None
    test_cases: int
    neo4j_ok: bool
    sqlite_ok: bool
    scan_build_ok: bool

    def to_dict(self) -> dict:
        return {
            "functions": self.functions,
            "graph_edges": self.graph_edges,
            "graph_nodes": self.graph_nodes,
            "coverage_pct": self.coverage_pct,
            "warnings": self.warnings,
            "scan_bugs": self.scan_bugs,
            "test_cases": self.test_cases,
            "neo4j_ok": self.neo4j_ok,
            "sqlite_ok": self.sqlite_ok,
            "scan_build_ok": self.scan_build_ok,
        }


_DEFAULTS = Stats(
    functions=0,
    graph_edges=0,
    graph_nodes=0,
    coverage_pct=0.0,
    warnings=0,
    scan_bugs=0,
    test_cases=0,
    neo4j_ok=False,
    sqlite_ok=False,
    scan_build_ok=False,
)


class StatsService:
    def __init__(self, pool: EnginePool, ttl_seconds: float):
        self._pool = pool
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._cached: Stats | None = None
        self._cached_at: float = 0.0

    def get(self) -> Stats:
        now = time.time()
        with self._lock:
            if self._cached is not None and (now - self._cached_at) < self._ttl:
                return self._cached
        fresh = self._compute()
        with self._lock:
            self._cached = fresh
            self._cached_at = time.time()
        return fresh

    def _compute(self) -> Stats:
        functions = _DEFAULTS.functions
        edges = 0
        nodes = 0
        neo4j_ok = False
        try:
            with self._pool.neo4j_session() as s:
                r = s.run(
                    "MATCH (f:Function) WITH count(f) AS fc "
                    "MATCH (n) WITH fc, count(n) AS nc "
                    "MATCH ()-[e]->() RETURN fc, nc, count(e) AS ec"
                ).single()
                if r:
                    functions = int(r["fc"])
                    nodes = int(r["nc"])
                    edges = int(r["ec"])
            neo4j_ok = True
        except Exception as e:  # noqa: BLE001
            log.info("stats: neo4j unavailable (%s)", e)

        cov_pct = 0.0
        tests = 0
        sqlite_ok = False
        try:
            conn = self._pool.sqlite()
            cur = conn.cursor()
            cur.execute(
                "WITH effective AS ("
                "  SELECT block_id, MAX(hit_count) AS hit_count "
                "  FROM coverage "
                "  GROUP BY block_id"
                ") "
                "SELECT "
                "  COALESCE(SUM(CASE WHEN hit_count > 0 THEN 1 ELSE 0 END), 0) AS covered, "
                "  COALESCE(COUNT(*), 0) AS total "
                "FROM effective"
            )
            row = cur.fetchone()
            if row and row["total"]:
                cov_pct = round(100.0 * row["covered"] / row["total"], 1)
            cur.execute("SELECT COUNT(*) AS n FROM test_cases")
            row = cur.fetchone()
            if row:
                tests = int(row["n"])
            sqlite_ok = True
        except sqlite3.Error as e:
            log.info("stats: sqlite unavailable (%s)", e)

        warnings, scan_bugs, scan_build_ok = _read_scan_build_stats()

        return Stats(
            functions=functions,
            graph_edges=edges,
            graph_nodes=nodes,
            coverage_pct=cov_pct,
            warnings=warnings,
            scan_bugs=scan_bugs,
            test_cases=tests,
            neo4j_ok=neo4j_ok,
            sqlite_ok=sqlite_ok,
            scan_build_ok=scan_build_ok,
        )


def _read_scan_build_stats() -> tuple[int | None, int | None, bool]:
    path = Path(__file__).resolve().parents[3] / "data" / "scan-build-output.txt"
    if not path.exists():
        return None, None, False

    text = path.read_text(errors="replace")
    warning_count = sum(1 for line in text.splitlines() if "warning:" in line)

    bugs_found = None
    match = re.search(r"\b(\d+)\s+bugs?\s+found\b", text, re.IGNORECASE)
    if match:
        bugs_found = int(match.group(1))
    elif re.search(r"\bNo\s+bugs\s+found\b", text, re.IGNORECASE):
        bugs_found = 0

    return warning_count, bugs_found, True
