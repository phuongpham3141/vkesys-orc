"""WSGI entry point for production deployment (gunicorn / waitress)."""
from app import create_app

application = create_app()
app = application
