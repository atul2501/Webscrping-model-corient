import os

from flask import Flask, jsonify, request
from sqlalchemy import event

from app.config import Config
from app.extensions import db, migrate
from app.utils.logging import configure_logging


def create_app(config_object=None):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_object or Config)

    os.makedirs(app.instance_path, exist_ok=True)
    _ensure_sqlite_dir(app.config["SQLALCHEMY_DATABASE_URI"])

    configure_logging(app.config.get("LOG_LEVEL", "INFO"))

    db.init_app(app)
    migrate.init_app(app, db)

    # The UI intentionally fires requests concurrently (an instant catalog
    # lookup alongside a live search, or two searches close together), and
    # the dev server runs threaded to actually serve them in parallel - so
    # SQLite's default locking (fails immediately as "database is locked" on
    # any write contention, no retry) is a real, hittable bug here, not a
    # theoretical one. WAL mode lets readers and a writer coexist, and a
    # busy_timeout makes a second writer wait briefly and retry instead of
    # failing outright. Postgres (docker-compose/Render) doesn't need this -
    # it handles concurrent writes natively.
    if app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite"):
        with app.app_context():

            @event.listens_for(db.engine, "connect")
            def _set_sqlite_pragma(dbapi_connection, _connection_record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.close()

    from app import models  # noqa: F401 - registers models with SQLAlchemy metadata
    from app.routes.api import api_bp
    from app.routes.views import views_bp

    app.register_blueprint(views_bp)
    app.register_blueprint(api_bp)

    # SQLite is the zero-setup local path (spec: "SQLite acceptable"); create
    # tables automatically there so `flask run` works with no extra steps.
    # Postgres (spec: "preferred", used by docker-compose) goes through the
    # real Alembic migrations in migrations/ via `flask db upgrade`.
    skip_autocreate = os.environ.get("FLASK_SKIP_AUTOCREATE") == "1"
    if (
        app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite")
        and not app.config.get("TESTING")
        and not skip_autocreate
    ):
        with app.app_context():
            db.create_all()

    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "not found"}), 404
        return "Not found", 404

    @app.errorhandler(500)
    def server_error(_error):
        if request.path.startswith("/api/"):
            return jsonify({"error": "internal server error"}), 500
        return "Internal server error", 500

    return app


def _ensure_sqlite_dir(database_uri: str) -> None:
    prefix = "sqlite:///"
    if not database_uri.startswith(prefix) or database_uri == "sqlite:///:memory:":
        return
    db_path = database_uri[len(prefix):]
    directory = os.path.dirname(db_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
