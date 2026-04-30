"""Development / production entry point for the VIC OCR Flask application.

Defaults to **waitress** — a real production-grade WSGI server with a fixed
thread pool that cleanly serves the web while OCR runs in subprocesses.
Werkzeug dev server stays available behind ``USE_WAITRESS=false`` for
people who really want auto-reload + interactive debugger.
"""
from __future__ import annotations

import os

from app import create_app

app = create_app()


def _bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", "8000"))
    debug = os.getenv("FLASK_ENV", "development") == "development"
    use_waitress = _bool(os.getenv("USE_WAITRESS"), True)

    if use_waitress:
        from waitress import serve

        threads = int(os.getenv("WAITRESS_THREADS", "16"))
        connection_limit = int(os.getenv("WAITRESS_CONNECTION_LIMIT", "200"))
        print(
            f" * Serving with waitress on http://{host}:{port}  "
            f"(threads={threads}, conn_limit={connection_limit})"
        )
        serve(
            app,
            host=host,
            port=port,
            threads=threads,
            connection_limit=connection_limit,
            channel_timeout=120,
            cleanup_interval=30,
            ident="vic-ocr",
        )
    else:
        # Werkzeug dev server — auto-reloader off by default because it
        # races with long-running OCR threads.
        use_reloader = debug and _bool(os.getenv("FLASK_AUTO_RELOAD"), False)
        print(f" * Werkzeug dev server on http://{host}:{port} (reloader={use_reloader})")
        app.run(host=host, port=port, debug=debug, use_reloader=use_reloader, threaded=True)
