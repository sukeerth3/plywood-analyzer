"""Aggregate stats endpoint, cached via StatsService."""
from flask import Blueprint, current_app, jsonify

from ..services.stats_service import StatsService

bp = Blueprint("stats", __name__, url_prefix="/api")


def _service() -> StatsService:
    if "stats_service" not in current_app.extensions:
        current_app.extensions["stats_service"] = StatsService(
            pool=current_app.extensions["engine_pool"],
            ttl_seconds=current_app.config["STATS_CACHE_TTL_SECONDS"],
        )
    return current_app.extensions["stats_service"]


@bp.get("/stats")
def stats():
    return jsonify(_service().get().to_dict())
