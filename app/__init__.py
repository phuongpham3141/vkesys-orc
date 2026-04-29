"""Flask application factory.

Wires up configuration, extensions, blueprints, logging and bootstrap data.
"""
from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from flask import Flask, render_template

from .config import BaseConfig, get_config
from .extensions import csrf, db, limiter, login_manager, migrate


def create_app(config_class: type[BaseConfig] | None = None) -> Flask:
    """Create and configure a Flask application instance."""
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(config_class or get_config())

    _ensure_directories(app)
    _configure_logging(app)
    _init_extensions(app)
    _register_blueprints(app)
    _register_error_handlers(app)
    _register_cli(app)

    with app.app_context():
        from . import models  # noqa: F401  - ensure models are imported
        _bootstrap_admin(app)
        _start_folder_watcher(app)

    return app


def _ensure_directories(app: Flask) -> None:
    paths = [
        app.config["UPLOAD_FOLDER"],
        app.config["OUTPUT_FOLDER"],
        app.config["WATCH_FOLDER_PATH"],
        app.config["WATCH_FOLDER_PROCESSED_PATH"],
        Path(app.root_path).parent / "credentials",
        Path(app.root_path).parent / "logs",
    ]
    for raw in paths:
        Path(raw).mkdir(parents=True, exist_ok=True)


def _configure_logging(app: Flask) -> None:
    log_dir = Path(app.root_path).parent / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    handler = RotatingFileHandler(
        log_dir / "app.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("[%(asctime)s] %(levelname)s in %(module)s: %(message)s")
    )
    handler.setLevel(logging.INFO)

    if not any(isinstance(h, RotatingFileHandler) for h in app.logger.handlers):
        app.logger.addHandler(handler)
    app.logger.setLevel(logging.INFO)
    app.logger.info("VIC OCR application starting up")


def _init_extensions(app: Flask) -> None:
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)

    from .models import User

    @login_manager.user_loader
    def load_user(user_id: str) -> User | None:  # type: ignore[name-defined]
        try:
            return db.session.get(User, int(user_id))
        except (TypeError, ValueError):
            return None


def _register_blueprints(app: Flask) -> None:
    from .admin.routes import admin_bp
    from .api.routes import api_bp
    from .auth.routes import auth_bp
    from .main.routes import main_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp, url_prefix="/auth")
    app.register_blueprint(admin_bp, url_prefix="/admin")
    app.register_blueprint(api_bp, url_prefix="/api/v1")
    csrf.exempt(api_bp)


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(404)
    def not_found(_error):  # type: ignore[no-untyped-def]
        return render_template("errors/404.html"), 404

    @app.errorhandler(500)
    def server_error(error):  # type: ignore[no-untyped-def]
        app.logger.exception("Unhandled server error: %s", error)
        return render_template("errors/500.html"), 500


def _register_cli(app: Flask) -> None:
    import click

    from .models import User

    @app.cli.command("create-admin")
    @click.option("--username", default="admin")
    @click.option("--email", default="admin@local")
    @click.option("--password", default="admin123")
    def create_admin(username: str, email: str, password: str) -> None:
        """Create or reset the default admin account."""
        existing = User.query.filter_by(username=username).first()
        if existing is None:
            user = User(username=username, email=email, role="admin")
            user.set_password(password)
            db.session.add(user)
            click.echo(f"Admin user '{username}' created.")
        else:
            existing.set_password(password)
            existing.role = "admin"
            click.echo(f"Admin user '{username}' password reset.")
        db.session.commit()


def _ensure_schema(app: Flask) -> None:
    """Idempotently align the live schema with the current models.

    Runs ``CREATE TABLE IF NOT EXISTS`` via ``db.create_all`` first, then
    issues ``ALTER TABLE ... ADD COLUMN IF NOT EXISTS`` for each column that
    was added after the initial schema. Used as a self-heal so that adding
    new model columns does not require the user to run ``flask db migrate``.
    """
    from sqlalchemy import text

    db.create_all()

    additive = [
        # (table, column, ddl_type)
        ("user_ocr_configs", "documentai_project_id", "VARCHAR(128)"),
        ("user_ocr_configs", "documentai_location", "VARCHAR(32)"),
        ("user_ocr_configs", "documentai_processor_id", "VARCHAR(128)"),
        ("user_ocr_configs", "gemini_api_key_encrypted", "TEXT"),
        ("user_ocr_configs", "gemini_model", "VARCHAR(64)"),
        ("users", "must_change_password", "BOOLEAN NOT NULL DEFAULT FALSE"),
        ("ocr_jobs", "target_pages", "JSONB"),
    ]
    for table, column, ddl in additive:
        try:
            with db.engine.begin() as conn:
                conn.execute(
                    text(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {ddl}')
                )
        except Exception as exc:  # pragma: no cover - defensive
            app.logger.warning(
                "Schema ensure: ALTER %s.%s skipped (%s)", table, column, exc
            )


def _bootstrap_admin(app: Flask) -> None:
    """Create default admin user on first run.

    Falls back to ``_ensure_schema()`` if migrations have not been applied.
    """
    from sqlalchemy import inspect

    from .models import User

    try:
        inspector = inspect(db.engine)
        if "users" not in inspector.get_table_names():
            app.logger.warning(
                "Tables missing — running _ensure_schema() as fallback"
            )
            _ensure_schema(app)
            inspector = inspect(db.engine)
            if "users" not in inspector.get_table_names():
                app.logger.error("Schema bootstrap failed to create 'users' table")
                return
        else:
            _ensure_schema(app)

        if db.session.query(User).count() > 0:
            return
        admin = User(
            username="admin",
            email="admin@local",
            role="admin",
            must_change_password=True,
        )
        admin.set_password("admin123")
        admin.regenerate_api_token()
        db.session.add(admin)
        db.session.commit()
        app.logger.info("Bootstrapped default admin user (admin/admin123)")
    except Exception as exc:  # pragma: no cover - defensive
        app.logger.warning("Could not bootstrap admin user: %s", exc)
        db.session.rollback()


def _start_folder_watcher(app: Flask) -> None:
    if not app.config.get("FOLDER_WATCH_ENABLED"):
        return
    # Avoid double-launch under Werkzeug debug reloader.
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true" and app.debug:
        return
    from .services.folder_watcher import start_watcher

    start_watcher(app)
