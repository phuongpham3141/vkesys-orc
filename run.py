"""Development entry point for the VIC OCR Flask application."""
from __future__ import annotations

import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", "8000"))
    debug = os.getenv("FLASK_ENV", "development") == "development"
    # Werkzeug's auto-reloader races with long-running OCR threads and
    # leaves stale sockets (WinError 10038). Off by default; opt-in via env.
    use_reloader = (
        debug and os.getenv("FLASK_AUTO_RELOAD", "false").lower() in {"1", "true", "yes"}
    )
    app.run(host=host, port=port, debug=debug, use_reloader=use_reloader)
