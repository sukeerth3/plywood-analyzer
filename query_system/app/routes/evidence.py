"""Evidence endpoints for storage and source workbench views."""
from flask import Blueprint, current_app, jsonify

from ..errors import AppError
from ..services.evidence_service import EvidenceService

bp = Blueprint("evidence", __name__, url_prefix="/api/evidence")


def _service() -> EvidenceService:
    if "evidence_service" not in current_app.extensions:
        current_app.extensions["evidence_service"] = EvidenceService(
            current_app.extensions["engine_pool"],
            ttl_seconds=current_app.config["STATS_CACHE_TTL_SECONDS"],
        )
    return current_app.extensions["evidence_service"]


@bp.get("/neo4j")
def neo4j():
    try:
        return jsonify(_service().neo4j())
    except Exception as e:  # noqa: BLE001
        raise AppError(
            "backend_unavailable",
            f"Neo4j evidence is unavailable: {str(e)[:300]}",
            503,
        )


@bp.get("/sqlite")
def sqlite():
    try:
        return jsonify(_service().sqlite())
    except Exception as e:  # noqa: BLE001
        raise AppError(
            "backend_unavailable",
            f"SQLite evidence is unavailable: {str(e)[:300]}",
            503,
        )


@bp.get("/coverage/uncovered")
def uncovered():
    try:
        return jsonify(_service().uncovered())
    except Exception as e:  # noqa: BLE001
        raise AppError(
            "backend_unavailable",
            f"Coverage evidence is unavailable: {str(e)[:300]}",
            503,
        )


@bp.get("/coverage/delta")
def coverage_delta():
    try:
        return jsonify(_service().coverage_delta())
    except Exception as e:  # noqa: BLE001
        raise AppError(
            "backend_unavailable",
            f"Coverage delta is unavailable: {str(e)[:300]}",
            503,
        )
