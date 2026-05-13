"""Evidence feeds backed by Neo4j and SQLite."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Any

from analysis.graph_importer import _demangle

from .engine_pool import EnginePool

log = logging.getLogger("plywood.evidence")

LABELS = ("Function", "BasicBlock", "Variable")
REL_TYPES = ("CALLS", "ENTRY_BLOCK", "SUCCESSOR", "DEPENDS_ON")


@dataclass
class _CacheEntry:
    value: dict[str, Any]
    cached_at: float


class EvidenceService:
    def __init__(self, pool: EnginePool, ttl_seconds: float):
        self._pool = pool
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._cache: dict[str, _CacheEntry] = {}

    def neo4j(self) -> dict[str, Any]:
        return self._cached("neo4j", self._compute_neo4j)

    def sqlite(self) -> dict[str, Any]:
        return self._cached("sqlite", self._compute_sqlite)

    def uncovered(self) -> dict[str, Any]:
        return self._compute_uncovered()

    def coverage_delta(self) -> dict[str, Any]:
        return self._compute_coverage_delta()

    def _cached(self, key: str, compute):
        now = time.time()
        with self._lock:
            entry = self._cache.get(key)
            if entry and now - entry.cached_at < self._ttl:
                return entry.value

        fresh = compute()
        with self._lock:
            self._cache[key] = _CacheEntry(value=fresh, cached_at=time.time())
        return fresh

    def _compute_neo4j(self) -> dict[str, Any]:
        with self._pool.neo4j_session() as session:
            label_counts = dict.fromkeys(LABELS, 0)
            for label in LABELS:
                row = session.run(f"MATCH (n:{label}) RETURN count(n) AS n").single()
                label_counts[label] = int(row["n"]) if row else 0

            rel_counts = dict.fromkeys(REL_TYPES, 0)
            rows = session.run(
                "MATCH ()-[r]->() "
                "RETURN type(r) AS type, count(r) AS n "
                "ORDER BY type"
            )
            for row in rows:
                rel_type = row["type"]
                if rel_type in rel_counts:
                    rel_counts[rel_type] = int(row["n"])

            calls = [
                [row["source"], row["target"]]
                for row in session.run(
                    "MATCH (a:Function)-[:CALLS]->(b:Function) "
                    "RETURN a.name AS source, b.name AS target "
                    "ORDER BY source, target "
                    "LIMIT 8"
                )
            ]

            depends_on = [
                [
                    _scoped_name(row["source"], row["source_function"]),
                    _scoped_name(row["target"], row["target_function"]),
                ]
                for row in session.run(
                    "MATCH (a:Variable)-[:DEPENDS_ON]->(b:Variable) "
                    "RETURN a.name AS source, a.function AS source_function, "
                    "       b.name AS target, b.function AS target_function "
                    "ORDER BY source_function, source, target_function, target "
                    "LIMIT 8"
                )
            ]

        return {
            "labels": label_counts,
            "relationships": rel_counts,
            "samples": {
                "calls": calls,
                "depends_on": depends_on,
            },
        }

    def _compute_sqlite(self) -> dict[str, Any]:
        conn = self._pool.sqlite()
        table_counts = {}
        for table in ("coverage", "test_cases", "fuzz_stats"):
            row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
            table_counts[table] = int(row["n"]) if row else 0

        effective_cte = """
            WITH effective AS (
                SELECT function, block_id,
                       MIN(line_start) AS line_start,
                       MIN(line_end) AS line_end,
                       MAX(hit_count) AS hit_count
                FROM coverage
                GROUP BY function, block_id
            )
        """

        row = conn.execute(
            effective_cte +
            "SELECT "
            "  COUNT(*) AS total_blocks, "
            "  COALESCE(SUM(CASE WHEN hit_count > 0 THEN 1 ELSE 0 END), 0) AS hit_blocks, "
            "  COALESCE(SUM(CASE WHEN hit_count = 0 THEN 1 ELSE 0 END), 0) AS uncovered_blocks "
            "FROM effective"
        ).fetchone()
        total = int(row["total_blocks"]) if row else 0
        hit = int(row["hit_blocks"]) if row else 0
        uncovered = int(row["uncovered_blocks"]) if row else 0
        coverage_pct = round(100.0 * hit / total, 1) if total else 0.0

        by_function = [
            {
                "function": r["function"],
                "total": int(r["total"]),
                "uncovered": int(r["uncovered"]),
            }
            for r in conn.execute(
                effective_cte +
                "SELECT function, COUNT(*) AS total, "
                "       COALESCE(SUM(CASE WHEN hit_count = 0 THEN 1 ELSE 0 END), 0) AS uncovered "
                "FROM effective "
                "GROUP BY function "
                "ORDER BY function"
            )
        ]

        fuzz = [_row_to_dict(r) for r in conn.execute("SELECT * FROM fuzz_stats ORDER BY source")]

        row = conn.execute(
            "SELECT "
            "  COUNT(*) AS total, "
            "  COALESCE(SUM(CASE WHEN passed THEN 1 ELSE 0 END), 0) AS passed "
            "FROM test_cases"
        ).fetchone()
        test_total = int(row["total"]) if row else 0
        test_passed = int(row["passed"]) if row else 0
        differential_pass_rate = (
            round(100.0 * test_passed / test_total, 1)
            if test_total
            else 0.0
        )

        return {
            "tables": table_counts,
            "coverage": {
                "total_blocks": total,
                "hit_blocks": hit,
                "uncovered_blocks": uncovered,
                "coverage_pct": coverage_pct,
                "by_function": by_function,
            },
            "differential_pass_rate": differential_pass_rate,
            "differential_passed": test_passed,
            "differential_total": test_total,
            "fuzz": fuzz,
        }

    def _compute_uncovered(self) -> dict[str, Any]:
        rows = [
            _row_to_dict(r)
            for r in self._pool.sqlite().execute(
                "WITH effective AS ("
                "  SELECT function, block_id, "
                "         MIN(line_start) AS line_start, "
                "         MIN(line_end) AS line_end, "
                "         MAX(hit_count) AS hit_count, "
                "         GROUP_CONCAT(source) AS source "
                "  FROM coverage "
                "  GROUP BY function, block_id"
                ") "
                "SELECT function, block_id, line_start, line_end, hit_count, NULL AS branch_taken, source "
                "FROM effective "
                "WHERE hit_count = 0 "
                "ORDER BY function, line_start, block_id"
            )
        ]
        return {"rows": rows, "count": len(rows)}

    def _compute_coverage_delta(self) -> dict[str, Any]:
        conn = self._pool.sqlite()

        baseline = _coverage_source_summary(conn, "gcov_curated")
        replay = _coverage_source_summary(conn, "gcov_afl_replay")

        blocks_added = [
            {
                "function": r["function"],
                "block_id": r["block_id"],
                "line_start": r["line_start"],
                "line_end": r["line_end"],
            }
            for r in conn.execute(
                "SELECT r.function, r.block_id, r.line_start, r.line_end "
                "FROM coverage r "
                "LEFT JOIN coverage b "
                "  ON b.block_id = r.block_id AND b.source = 'gcov_curated' "
                "WHERE r.source = 'gcov_afl_replay' "
                "  AND r.hit_count > 0 "
                "  AND COALESCE(b.hit_count, 0) = 0 "
                "ORDER BY r.function, r.line_start, r.block_id"
            )
        ]

        try:
            row = conn.execute(
                "SELECT COALESCE(MAX(afl_replay_count), 0) AS n FROM fuzz_stats"
            ).fetchone()
            replay_count = int(row["n"]) if row else 0
        except sqlite3.OperationalError:
            replay_count = 0

        return {
            "baseline": baseline,
            "replay": replay,
            "blocks_added_by_replay": blocks_added,
            "afl_queue_inputs_replayed": replay_count,
        }


def _scoped_name(name: str, function: str) -> str:
    return f"{name}@{_demangle(function) or function}"


def _coverage_source_summary(conn: sqlite3.Connection, source: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT "
        "  COUNT(*) AS total_blocks, "
        "  COALESCE(SUM(CASE WHEN hit_count > 0 THEN 1 ELSE 0 END), 0) AS hit_blocks "
        "FROM coverage "
        "WHERE source = ?",
        (source,),
    ).fetchone()
    total = int(row["total_blocks"]) if row else 0
    hit = int(row["hit_blocks"]) if row else 0
    return {
        "total_blocks": total,
        "hit_blocks": hit,
        "pct": round(100.0 * hit / total, 1) if total else 0.0,
    }


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}
