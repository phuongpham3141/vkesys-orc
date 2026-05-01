"""Google OAuth login flow using Authlib.

Optional — only enabled when GOOGLE_OAUTH_CLIENT_ID + CLIENT_SECRET are
present in the config. Routes:

    GET  /auth/google         -> redirect to Google's consent page
    GET  /auth/google/callback -> handle the OAuth response, login or
                                  create a User record, redirect to /

Set up in GCP: see docs/GOOGLE_OAUTH_SETUP.md.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Optional

from authlib.integrations.base_client.errors import MismatchingStateError
from authlib.integrations.flask_client import OAuth
from flask import Blueprint, current_app, flash, redirect, request, session, url_for
from flask_login import current_user, login_user

from ..extensions import db
from ..models import User

oauth_bp = Blueprint("oauth", __name__)

# Lazily initialised OAuth registry; init_app() called from app factory.
oauth = OAuth()


def init_oauth(app) -> None:
    """Register the Google OAuth client only when credentials are configured."""
    oauth.init_app(app)
    client_id = app.config.get("GOOGLE_OAUTH_CLIENT_ID") or ""
    client_secret = app.config.get("GOOGLE_OAUTH_CLIENT_SECRET") or ""
    if not (client_id and client_secret):
        app.logger.info("Google OAuth: not configured (skipping)")
        return
    oauth.register(
        name="google",
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )
    app.logger.info("Google OAuth: registered (client_id=%s...)", client_id[:12])


def google_oauth_enabled() -> bool:
    return bool(
        current_app.config.get("GOOGLE_OAUTH_CLIENT_ID")
        and current_app.config.get("GOOGLE_OAUTH_CLIENT_SECRET")
    )


def _redirect_uri() -> str:
    override = current_app.config.get("OAUTH_REDIRECT_URI")
    if override:
        return override
    return url_for("oauth.google_callback", _external=True)


@oauth_bp.route("/google")
def google_login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if not google_oauth_enabled():
        flash("Google OAuth chưa được cấu hình.", "error")
        return redirect(url_for("auth.login"))
    # Mark session as permanent so the OAuth state cookie survives the
    # round-trip to Google and back (default Flask sessions can be browser-
    # closure-tied; permanent ones use PERMANENT_SESSION_LIFETIME).
    session.permanent = True
    # Drop any stale state from a half-finished previous attempt so we
    # don't end up with two states fighting in the same session.
    for key in list(session.keys()):
        if key.startswith("_state_google_"):
            session.pop(key, None)
    return oauth.google.authorize_redirect(_redirect_uri())


@oauth_bp.route("/google/callback")
def google_callback():
    if not google_oauth_enabled():
        flash("Google OAuth chưa được cấu hình.", "error")
        return redirect(url_for("auth.login"))
    try:
        token = oauth.google.authorize_access_token()
    except MismatchingStateError:
        # Most common causes:
        #  - user's session cookie didn't survive the redirect to Google
        #    (third-party cookie blocking, multiple tabs, very old session)
        #  - user clicked the Google button twice → first state overwrote
        #  - Cloudflare / nginx stripped or rewrote the session cookie
        # Friendly retry path; almost always works on the second click.
        current_app.logger.warning(
            "Google OAuth state mismatch (session probably lost). "
            "Session keys: %s",
            [k for k in session.keys() if not k.startswith("_csrf")],
        )
        # Wipe whatever stale state remains so the next click starts clean.
        for key in list(session.keys()):
            if key.startswith("_state_google_"):
                session.pop(key, None)
        flash(
            "Phiên đăng nhập Google đã hết hạn hoặc bị mất "
            "(thường do mở nhiều tab/cookie bị chặn). Hãy thử lại.",
            "warning",
        )
        return redirect(url_for("auth.login"))
    except Exception as exc:  # pragma: no cover - external service errors
        current_app.logger.exception("Google OAuth token exchange failed")
        flash(f"Google OAuth thất bại: {exc}", "error")
        return redirect(url_for("auth.login"))

    userinfo = token.get("userinfo") or {}
    if not userinfo:
        try:
            userinfo = oauth.google.userinfo(token=token)
        except Exception:
            userinfo = {}

    sub = userinfo.get("sub")
    email = (userinfo.get("email") or "").strip().lower()
    name = userinfo.get("name") or userinfo.get("given_name") or ""
    picture = userinfo.get("picture")

    if not (sub and email):
        flash("Không lấy được thông tin Google. Thử lại.", "error")
        return redirect(url_for("auth.login"))

    user = (
        User.query.filter_by(oauth_provider="google", oauth_uid=sub).first()
        or User.query.filter_by(email=email).first()
    )

    if user is None:
        # First-time sign-in: create a fresh account.
        username = _unique_username_from(email, name)
        user = User(
            username=username,
            email=email,
            role="user",
            oauth_provider="google",
            oauth_uid=sub,
            avatar_url=picture,
            is_active=True,
            must_change_password=False,
        )
        # Random password — user can later change it via /auth/profile.
        user.set_password(secrets.token_urlsafe(24))
        user.regenerate_api_token()
        db.session.add(user)
        db.session.commit()
        flash(f"Chào mừng, {user.username}! Tài khoản đã được tạo từ Google.", "success")
    else:
        # Link existing account to Google if not already linked.
        if not user.oauth_provider:
            user.oauth_provider = "google"
            user.oauth_uid = sub
        if picture and not user.avatar_url:
            user.avatar_url = picture
        if not user.is_active:
            flash("Tài khoản này đã bị khoá.", "error")
            return redirect(url_for("auth.login"))
        db.session.commit()

    user.last_login = datetime.utcnow()
    db.session.commit()
    login_user(user, remember=True)
    return redirect(url_for("main.dashboard"))


def _unique_username_from(email: str, full_name: str) -> str:
    """Pick a username from email local-part, falling back with a random suffix."""
    base = (email.split("@", 1)[0] if "@" in email else full_name).strip().lower()
    base = "".join(c for c in base if c.isalnum() or c in "._-") or "user"
    candidate = base
    suffix = 0
    while User.query.filter_by(username=candidate).first() is not None:
        suffix += 1
        candidate = f"{base}{suffix}"
        if suffix > 50:
            candidate = f"{base}-{secrets.token_hex(3)}"
            break
    return candidate
