"""Flask application factory."""
from flask import Flask
from flask_cors import CORS

from .config import Config
from .logging import configure_logging, install_request_id
from .errors import register_error_handlers
from .services.engine_pool import EnginePool
from .routes import health, stats, source, demo, query, schema, ui, options, evidence


def create_app(config: Config | None = None) -> Flask:
    cfg = config or Config.from_env()

    app = Flask(
        __name__,
        static_folder="../static",
        template_folder="../templates",
        static_url_path="/static",
    )
    app.config.from_object(cfg)

    CORS(app, resources={r"/api/*": {"origins": cfg.CORS_ORIGINS}})

    configure_logging(cfg.LOG_LEVEL)
    install_request_id(app)
    register_error_handlers(app)

    app.extensions["engine_pool"] = EnginePool(
        neo4j_uri=cfg.NEO4J_URI,
        neo4j_user=cfg.NEO4J_USER,
        neo4j_password=cfg.NEO4J_PASSWORD,
        sqlite_path=cfg.SQLITE_DB,
    )

    app.register_blueprint(ui.bp)
    app.register_blueprint(health.bp)
    app.register_blueprint(stats.bp)
    app.register_blueprint(source.bp)
    app.register_blueprint(demo.bp)
    app.register_blueprint(options.bp)
    app.register_blueprint(evidence.bp)
    app.register_blueprint(query.bp)
    app.register_blueprint(schema.bp)

    @app.teardown_appcontext
    def _teardown(_exc):
        # Per-request resources are released inside the pool; nothing to do here.
        pass

    return app
