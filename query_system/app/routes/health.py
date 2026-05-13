"""Liveness + readiness probes.

`/api/health`  — liveness. 200 as long as the Flask app itself is responsive.
`/api/ready`   — readiness. 200 only when all required backends are up.
"""
from flask import Blueprint, current_app, jsonify

bp = Blueprint("health", __name__, url_prefix="/api")


@bp.get("/health")
def health():
    pool = current_app.extensions["engine_pool"]
    return jsonify(
        {
            "status": "ok",
            "neo4j": "ok" if pool.neo4j_ping() else "unavailable",
        }
    )


@bp.get("/ready")
def ready():
    pool = current_app.extensions["engine_pool"]
    neo4j_ok = pool.neo4j_ping()
    sqlite_ok = True
    try:
        conn = pool.sqlite()
        conn.execute("SELECT 1").fetchone()
    except Exception:  # noqa: BLE001
        sqlite_ok = False
    ready = neo4j_ok and sqlite_ok
    body = {"ready": ready, "neo4j": neo4j_ok, "sqlite": sqlite_ok}
    return jsonify(body), (200 if ready else 503)
