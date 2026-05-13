"""Structured JSON logging + per-request correlation IDs."""
from __future__ import annotations

import json
import logging
import time
import uuid
from flask import Flask, g, request


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        rid = getattr(record, "request_id", None)
        if rid:
            payload["request_id"] = rid
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for k in ("method", "path", "status", "duration_ms"):
            if hasattr(record, k):
                payload[k] = getattr(record, k)
        return json.dumps(payload, ensure_ascii=False)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.request_id = getattr(g, "request_id", None)
        except RuntimeError:
            record.request_id = None
        return True


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    # Idempotent reconfigure: drop old handlers so reloader doesn't stack them.
    for h in list(root.handlers):
        root.removeHandler(h)
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RequestIdFilter())
    root.addHandler(handler)
    root.setLevel(level.upper())
    # Werkzeug's access log is noisy and duplicates our own — mute it.
    logging.getLogger("werkzeug").setLevel(logging.WARNING)


def install_request_id(app: Flask) -> None:
    log = logging.getLogger("plywood.access")

    @app.before_request
    def _start():
        g.request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
        g.t0 = time.perf_counter()

    @app.after_request
    def _finish(response):
        rid = getattr(g, "request_id", None)
        if rid:
            response.headers["X-Request-ID"] = rid
        t0 = getattr(g, "t0", None)
        duration_ms = round((time.perf_counter() - t0) * 1000, 2) if t0 is not None else None
        log.info(
            "%s %s -> %s",
            request.method,
            request.path,
            response.status_code,
            extra={
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response
