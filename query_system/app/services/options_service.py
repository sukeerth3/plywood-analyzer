"""Option feeds for parameterized demo query controls."""
from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from analysis.graph_importer import _demangle

from .engine_pool import EnginePool

log = logging.getLogger("plywood.options")


class OptionsService:
    def __init__(self, pool: EnginePool, project_root: str):
        self._pool = pool
        self._root = Path(project_root)

    def functions(self) -> dict:
        try:
            with self._pool.neo4j_session() as session:
                rows = session.run(
                    "MATCH (f:Function) "
                    "RETURN f.name AS name "
                    "ORDER BY f.name"
                )
                names = [r["name"] for r in rows if r["name"]]
            return {"functions": names, "source": "neo4j"}
        except Exception as e:  # noqa: BLE001
            log.info("options functions: neo4j unavailable (%s)", e)

        try:
            cur = self._pool.sqlite().cursor()
            cur.execute("SELECT DISTINCT function FROM coverage ORDER BY 1")
            names = [r["function"] for r in cur.fetchall() if r["function"]]
            return {"functions": names, "source": "sqlite"}
        except sqlite3.Error as e:
            log.info("options functions: sqlite unavailable (%s)", e)
            raise

    def variables(self, function_name: str) -> dict:
        try:
            with self._pool.neo4j_session() as session:
                rows = session.run(
                    "MATCH (v:Variable {function: $function}) "
                    "RETURN DISTINCT v.name AS name "
                    "ORDER BY v.name",
                    function=function_name,
                )
                names = [r["name"] for r in rows if r["name"]]
                if not names:
                    rows = session.run(
                        "MATCH (v:Variable) "
                        "RETURN DISTINCT v.name AS name, v.function AS function "
                        "ORDER BY v.name"
                    )
                    names = [
                        r["name"]
                        for r in rows
                        if r["name"] and _demangle(r["function"]) == function_name
                    ]
            return {"function": function_name, "variables": names, "source": "neo4j"}
        except Exception as e:  # noqa: BLE001
            log.info("options variables: neo4j unavailable (%s)", e)

        names = self._variables_from_dependencies(function_name)
        return {"function": function_name, "variables": names, "source": "dependencies_json"}

    def _variables_from_dependencies(self, function_name: str) -> list[str]:
        path = self._root / "data" / "dependencies.json"
        try:
            with path.open("r", encoding="utf-8") as f:
                deps = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            log.info("options variables: dependencies fallback unavailable (%s)", e)
            return []

        names: set[str] = set()
        for dep in deps:
            if _demangle(dep.get("function", "")) != function_name:
                continue
            if dep.get("from"):
                names.add(dep["from"])
            if dep.get("to"):
                names.add(dep["to"])
        return sorted(names)
