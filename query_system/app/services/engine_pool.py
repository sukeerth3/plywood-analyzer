"""Singleton-style Neo4j driver + lazy SQLite connection, shared across requests.

Design:
- One Neo4j driver per process (thread-safe, pools internally). Sessions are
  cheap and are taken per-request via `neo4j_session()`.
- SQLite connections are NOT thread-safe across the default driver; we give
  each thread its own read-only connection via a thread-local cache.
- Facade builds the same `QueryEngine` surface the rest of the codebase expects,
  but backed by the pooled resources instead of per-call .__init__ churn.
"""
from __future__ import annotations

import logging
import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator

from neo4j import GraphDatabase, Driver, Session

from query_system.query_engine import QueryEngine

log = logging.getLogger("plywood.pool")


class EnginePool:
    def __init__(self, *, neo4j_uri: str, neo4j_user: str, neo4j_password: str, sqlite_path: str):
        self._neo4j_uri = neo4j_uri
        self._neo4j_auth = (neo4j_user, neo4j_password)
        self._sqlite_path = sqlite_path
        self._driver: Driver | None = None
        self._driver_lock = threading.Lock()
        self._tls = threading.local()

    # Neo4j
    def _driver_or_create(self) -> Driver:
        if self._driver is None:
            with self._driver_lock:
                if self._driver is None:
                    log.info("opening neo4j driver uri=%s", self._neo4j_uri)
                    self._driver = GraphDatabase.driver(
                        self._neo4j_uri,
                        auth=self._neo4j_auth,
                        max_connection_pool_size=20,
                        connection_acquisition_timeout=5.0,
                    )
        return self._driver

    @contextmanager
    def neo4j_session(self) -> Iterator[Session]:
        driver = self._driver_or_create()
        with driver.session() as s:
            yield s

    def neo4j_ping(self) -> bool:
        try:
            with self.neo4j_session() as s:
                s.run("RETURN 1").consume()
            return True
        except Exception as e:  # noqa: BLE001
            log.warning("neo4j ping failed: %s", e)
            return False

    # SQLite
    def sqlite(self) -> sqlite3.Connection:
        conn = getattr(self._tls, "conn", None)
        if conn is None:
            log.info("opening sqlite conn path=%s thread=%s", self._sqlite_path, threading.get_ident())
            conn = sqlite3.connect(self._sqlite_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            self._tls.conn = conn
        return conn

    # QueryEngine facade
    @contextmanager
    def engine(self) -> Iterator[QueryEngine]:
        """
        Produce a QueryEngine whose resources come from this pool.

        QueryEngine expects `self.neo4j` (driver) and `self.sqlite` (connection)
        attributes; we inject pool-managed handles and neutralise its `.close()`
        so per-request teardown does not tear down the pool.
        """
        eng = QueryEngine.__new__(QueryEngine)
        eng.neo4j = self._driver_or_create()
        eng.sqlite = self.sqlite()
        eng.close = lambda: None  # type: ignore[method-assign]
        try:
            yield eng
        finally:
            pass

    # Shutdown
    def close(self) -> None:
        if self._driver is not None:
            try:
                self._driver.close()
            except Exception:  # noqa: BLE001
                log.exception("neo4j driver close failed")
        conn = getattr(self._tls, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                log.exception("sqlite close failed")
