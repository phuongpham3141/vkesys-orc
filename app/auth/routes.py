"""Authentication routes: register / login / logout / profile."""
from __future__ import annotations

from datetime import datetime

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import or_

from ..extensions import db
from ..models import User
from .forms import (
    ChangePasswordForm,
    LoginForm,
    RegenerateTokenForm,
    RegisterForm,
    UpdateProfileForm,
)

auth_bp = Blueprint("auth", __name__, template_folder="../templates/auth")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = LoginForm()
    if form.validate_on_submit():
        ident = form.identity.data.strip()
        user = User.query.filter(
            or_(User.username == ident, User.email == ident.lower())
        ).first()
        if user is None or not user.check_password(form.password.data):
            flash("Tên đăng nhập hoặc mật khẩu không đúng.", "error")
            return render_template("auth/login.html", form=form)
        if not user.is_active:
            flash("Tài khoản đã bị khoá.", "error")
            return render_template("auth/login.html", form=form)

        user.last_login = datetime.utcnow()
        db.session.commit()
        login_user(user, remember=form.remember.data)

        next_page = request.args.get("next")
        if next_page and next_page.startswith("/"):
            return redirect(next_page)
        return redirect(url_for("main.dashboard"))

    return render_template("auth/login.html", form=form)


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    form = RegisterForm()
    if form.validate_on_submit():
        user = User(
            username=form.username.data.strip(),
            email=form.email.data.strip().lower(),
            role="user",
        )
        user.set_password(form.password.data)
        user.regenerate_api_token()
        db.session.add(user)
        db.session.commit()
        flash("Đăng ký thành công! Vui lòng đăng nhập.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/register.html", form=form)


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Đã đăng xuất.", "info")
    return redirect(url_for("auth.login"))


@auth_bp.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    pwd_form = ChangePasswordForm(prefix="pwd")
    token_form = RegenerateTokenForm(prefix="token")
    profile_form = UpdateProfileForm(prefix="prof", email=current_user.email)

    if pwd_form.submit.data and pwd_form.validate_on_submit():
        if not current_user.check_password(pwd_form.current_password.data):
            flash("Mật khẩu hiện tại không đúng.", "error")
        else:
            current_user.set_password(pwd_form.new_password.data)
            current_user.must_change_password = False
            db.session.commit()
            flash("Đã đổi mật khẩu thành công.", "success")
            return redirect(url_for("auth.profile"))

    if token_form.submit.data and token_form.validate_on_submit():
        current_user.regenerate_api_token()
        db.session.commit()
        flash("Đã tạo API token mới.", "success")
        return redirect(url_for("auth.profile"))

    if profile_form.submit.data and profile_form.validate_on_submit():
        new_email = profile_form.email.data.strip().lower()
        if new_email != current_user.email:
            existing = User.query.filter_by(email=new_email).first()
            if existing and existing.id != current_user.id:
                flash("Email đã được dùng bởi tài khoản khác.", "error")
            else:
                current_user.email = new_email
                db.session.commit()
                flash("Đã cập nhật hồ sơ.", "success")
                return redirect(url_for("auth.profile"))

    return render_template(
        "auth/profile.html",
        pwd_form=pwd_form,
        token_form=token_form,
        profile_form=profile_form,
    )
