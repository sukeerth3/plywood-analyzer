"""Consistent JSON error envelope + global handlers.

Envelope:
  { "error": { "code": str, "message": str, "request_id": str } }
"""
from __future__ import annotations

import logging
from flask import Flask, g, jsonify
from werkzeug.exceptions import HTTPException

log = logging.getLogger("plywood.errors")


class AppError(Exception):
    """Raise from routes/services to produce a clean JSON error."""

    def __init__(self, code: str, message: str, status: int = 500):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


def _envelope(code: str, message: str, status: int):
    body = {
        "error": {
            "code": code,
            "message": message,
            "request_id": getattr(g, "request_id", None),
        }
    }
    return jsonify(body), status


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(AppError)
    def _app_error(e: AppError):
        log.warning("app_error code=%s status=%s: %s", e.code, e.status, e.message)
        return _envelope(e.code, e.message, e.status)

    @app.errorhandler(HTTPException)
    def _http_error(e: HTTPException):
        return _envelope(
            code=e.name.lower().replace(" ", "_"),
            message=e.description or e.name,
            status=e.code or 500,
        )

    @app.errorhandler(Exception)
    def _uncaught(e: Exception):
        log.exception("unhandled exception")
        return _envelope("internal_error", "An unexpected error occurred.", 500)
