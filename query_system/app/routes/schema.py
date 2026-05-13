"""SQLite schema endpoint."""
from flask import Blueprint, Response

from analysis.graph_importer import SCHEMA_DDL

bp = Blueprint("schema", __name__, url_prefix="/api")


@bp.get("/schema")
def schema():
    return Response(SCHEMA_DDL, mimetype="text/plain")
