"""Development server entrypoint for the Flask app."""
from __future__ import annotations

import logging
import signal

from query_system.app import create_app
from query_system.app.config import Config


def _install_shutdown_handlers(app) -> None:
    pool = app.extensions.get("engine_pool")
    if pool is None:
        return

    def _shutdown(signum, _frame):
        logging.getLogger("plywood").info("shutting down on signal %s", signum)
        pool.close()
        raise SystemExit(0)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _shutdown)
        except (ValueError, OSError):
            # Not on main thread (or Windows edge case); dev-server reloader handles it.
            pass


# Module-level `app` so gunicorn / `flask run` can find it too.
cfg = Config.from_env()
app = create_app(cfg)
_install_shutdown_handlers(app)


def main() -> None:
    # Dev server only; use a WSGI server (gunicorn/uwsgi) in production.
    app.run(host=cfg.HOST, port=cfg.PORT, debug=False)


if __name__ == "__main__":
    main()
