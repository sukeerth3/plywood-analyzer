"""Source file viewer endpoint."""
import os

from flask import Blueprint, current_app, jsonify, request

from ..errors import AppError
from ..services.source_service import SourceService
from .demo import _safe_ident

bp = Blueprint("source", __name__, url_prefix="/api")

_DEFAULT_PATH = "src/plywood_calc.cpp"


def _service() -> SourceService:
    if "source_service" not in current_app.extensions:
        root = os.path.abspath(
            os.path.join(current_app.root_path, "..", "..")
        )
        current_app.extensions["source_service"] = SourceService(
            project_root=root,
            ttl_seconds=current_app.config["SOURCE_CACHE_TTL_SECONDS"],
        )
    return current_app.extensions["source_service"]


@bp.get("/source")
def source():
    try:
        sf = _service().read(_DEFAULT_PATH)
    except FileNotFoundError:
        raise AppError("source_not_found", f"Source not found: {_DEFAULT_PATH}", 404)
    return jsonify({"path": sf.path, "lines": sf.lines, "source": sf.content})


@bp.get("/source/highlights")
def source_highlights():
    kind = _safe_ident(request.args.get("kind", ""), "uncovered", field="kind")
    if kind != "uncovered":
        raise AppError("invalid_argument", "Parameter 'kind' must be one of: uncovered.", 400)

    try:
        sf = _service().read(_DEFAULT_PATH)
    except FileNotFoundError:
        raise AppError("source_not_found", f"Source not found: {_DEFAULT_PATH}", 404)

    conn = current_app.extensions["engine_pool"].sqlite()
    rows = conn.execute(
        "WITH effective AS ("
        "  SELECT function, block_id, "
        "         MIN(line_start) AS line_start, "
        "         MAX(hit_count) AS hit_count "
        "  FROM coverage "
        "  GROUP BY function, block_id"
        ") "
        "SELECT function, block_id, line_start, hit_count "
        "FROM effective "
        "WHERE hit_count = 0 "
        "ORDER BY function, line_start, block_id"
    )
    highlights = [
        {
            "line": int(row["line_start"]),
            "kind": "uncovered-gcov-line-block",
            "function": row["function"],
            "block_id": row["block_id"],
            "hit_count": int(row["hit_count"]),
        }
        for row in rows
        if row["line_start"] is not None
    ]

    return jsonify({"path": sf.path, "lines": sf.lines, "highlights": highlights})
