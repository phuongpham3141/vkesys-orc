"""Tao bang neu thieu va reset/tao tai khoan admin voi mat khau chi dinh.

Chay: ``venv\\Scripts\\python.exe scripts\\reset_admin.py [<username>] [<password>]``

Mac dinh: username=admin, password=admin123 (de bo trong se dung default).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import create_app
from app.extensions import db
from app.models import User


def main() -> int:
    username = sys.argv[1] if len(sys.argv) > 1 else "admin"
    password = sys.argv[2] if len(sys.argv) > 2 else "admin123"

    app = create_app()
    with app.app_context():
        db.create_all()
        user = User.query.filter_by(username=username).first()
        if user is None:
            user = User(
                username=username,
                email=f"{username}@local",
                role="admin",
                is_active=True,
            )
            user.set_password(password)
            user.regenerate_api_token()
            user.must_change_password = False
            db.session.add(user)
            print(f"[OK] Tao moi user '{username}' (role=admin)")
        else:
            user.set_password(password)
            user.role = "admin"
            user.is_active = True
            user.must_change_password = False
            if not user.api_token:
                user.regenerate_api_token()
            print(f"[OK] Reset password cho user '{username}' (role=admin)")
        db.session.commit()
        print(f"     Username: {user.username}")
        print(f"     Email:    {user.email}")
        print(f"     Role:     {user.role}")
        print(f"     Token:    {user.api_token[:16]}...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
