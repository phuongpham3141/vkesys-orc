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


def _bootstrap_admin(app: Flask) -> None:
    """Create default admin user on first run.

    Falls back to ``db.create_all()`` if migrations have not yet been applied,
    so the app stays usable even when the launcher's flask-migrate step fails
    to autogenerate a version file.
    """
    from sqlalchemy import inspect

    from .models import User

    try:
        inspector = inspect(db.engine)
        if "users" not in inspector.get_table_names():
            app.logger.warning(
                "Table 'users' missing — running db.create_all() as fallback"
            )
            db.create_all()
            inspector = inspect(db.engine)
            if "users" not in inspector.get_table_names():
                app.logger.error("db.create_all() failed to create 'users' table")
                return

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
