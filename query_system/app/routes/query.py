"""Natural-language query endpoint."""
import logging

from flask import Blueprint, current_app, jsonify, request

from ..errors import AppError

bp = Blueprint("query", __name__, url_prefix="/api")
log = logging.getLogger("plywood.query")


@bp.post("/query")
def nl_query():
    payload = request.get_json(silent=True) or {}
    question = (payload.get("question") or "").strip()
    if not question:
        raise AppError("invalid_argument", "Field 'question' is required.", 400)
    max_len = current_app.config["NL_QUESTION_MAX_LEN"]
    if len(question) > max_len:
        raise AppError(
            "invalid_argument",
            f"Field 'question' exceeds {max_len} characters.",
            400,
        )

    pool = current_app.extensions["engine_pool"]
    try:
        with pool.engine() as engine:
            result = engine.nl_query(question)
    except Exception as e:  # noqa: BLE001
        log.exception("nl_query failed")
        raise AppError("query_failed", str(e)[:500], 500)

    # nl_query historically returns {"error": "..."} for API-key / parse issues;
    # convert those to the standard envelope with a useful status.
    if isinstance(result, dict) and "error" in result and len(result) <= 4:
        msg = result["error"]
        status = 503 if "ANTHROPIC_API_KEY" in msg else 502
        code = "llm_unconfigured" if status == 503 else "llm_failed"
        raise AppError(code, msg, status)

    return jsonify(result)
