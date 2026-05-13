"""Option endpoints for parameterized demo queries."""
import os
import sqlite3

from flask import Blueprint, current_app, jsonify, request

from ..errors import AppError
from ..services.options_service import OptionsService
from .demo import _safe_ident

bp = Blueprint("options", __name__, url_prefix="/api/options")


def _service() -> OptionsService:
    if "options_service" not in current_app.extensions:
        root = os.path.abspath(os.path.join(current_app.root_path, "..", ".."))
        current_app.extensions["options_service"] = OptionsService(
            current_app.extensions["engine_pool"],
            project_root=root,
        )
    return current_app.extensions["options_service"]


@bp.get("/functions")
def functions():
    try:
        return jsonify(_service().functions())
    except sqlite3.Error:
        raise AppError(
            "backend_unavailable",
            "Neither Neo4j nor SQLite is reachable for function options.",
            503,
        )


@bp.get("/variables")
def variables():
    function_name = _safe_ident(request.args.get("function", ""), "", field="function")
    return jsonify(_service().variables(function_name))
