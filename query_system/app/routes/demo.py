"""Deterministic demo queries (Q1, Q2, Q3, Q4).

All three return 503 with a useful envelope when Neo4j is down, so the
frontend can display a recovery hint instead of a 500.
"""
import logging
import re

from flask import Blueprint, current_app, jsonify, request

from ..errors import AppError

bp = Blueprint("demo", __name__, url_prefix="/api/demo")
log = logging.getLogger("plywood.demo")

# Loosely validate identifiers we accept as query parameters.
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:]*$")
_IDENT_MAX = 120


def _safe_ident(name: str, default: str, *, field: str) -> str:
    val = (name or "").strip() or default
    if len(val) > _IDENT_MAX or not _IDENT_RE.match(val):
        raise AppError(
            "invalid_argument",
            f"Parameter '{field}' must match {_IDENT_RE.pattern} and be <= {_IDENT_MAX} chars.",
            400,
        )
    return val


def _run(fn):
    pool = current_app.extensions["engine_pool"]
    try:
        with pool.engine() as engine:
            return jsonify(fn(engine))
    except AppError:
        raise
    except Exception as e:  # noqa: BLE001
        log.exception("demo query failed")
        msg = str(e)
        if "Couldn't connect" in msg or "Connection refused" in msg or "ServiceUnavailable" in msg:
            raise AppError(
                "backend_unavailable",
                "Neo4j is not reachable. Start it with `docker compose up -d neo4j`.",
                503,
            )
        raise AppError("query_failed", msg[:500], 500)


@bp.get("/1")
def q1():
    func = _safe_ident(request.args.get("func", ""), "calculate_cuts", field="func")
    return _run(lambda e: e.demo_q1_callers(func))


@bp.get("/2")
def q2():
    va = _safe_ident(request.args.get("var_a", ""), "board.length", field="var_a")
    vb = _safe_ident(request.args.get("var_b", ""), "rows_normal", field="var_b")
    vaf = request.args.get("var_a_func")
    vbf = request.args.get("var_b_func")
    if vaf is not None:
        vaf = _safe_ident(vaf, "", field="var_a_func")
    if vbf is not None:
        vbf = _safe_ident(vbf, "", field="var_b_func")
    return _run(lambda e: e.demo_q2_dependency(va, vb, var_a_func=vaf, var_b_func=vbf))


@bp.get("/3")
def q3():
    return _run(lambda e: e.demo_q3_uncovered())


@bp.get("/4")
def q4():
    return _run(lambda e: e.demo_q4_taint_reach())
