"""Admin user management routes."""
from __future__ import annotations

from functools import wraps

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, Length, Optional, Regexp

from ..extensions import db
from ..models import User
from ..services.settings import SETTING_DEFAULTS, list_settings, set_setting

admin_bp = Blueprint("admin", __name__, template_folder="../templates/admin")


def admin_required(view):
    """Restrict view to authenticated admins."""

    @wraps(view)
    @login_required
    def wrapper(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return view(*args, **kwargs)

    return wrapper


class UserForm(FlaskForm):
    username = StringField(
        "Tên đăng nhập",
        validators=[
            DataRequired(),
            Length(min=3, max=64),
            Regexp(r"^[A-Za-z0-9_.-]+$"),
        ],
    )
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    role = SelectField(
        "Vai trò",
        choices=[("user", "User"), ("admin", "Admin")],
        validators=[DataRequired()],
    )
    is_active = BooleanField("Kích hoạt", default=True)
    password = PasswordField(
        "Mật khẩu (để trống nếu không đổi)",
        validators=[Optional(), Length(min=8)],
    )
    submit = SubmitField("Lưu")


class DeleteForm(FlaskForm):
    submit = SubmitField("Xoá")


@admin_bp.route("/users")
@admin_required
def users():
    page = int(request.args.get("page", 1))
    per_page = 20
    query = User.query.order_by(User.created_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    return render_template(
        "admin/users.html",
        users=pagination.items,
        pagination=pagination,
        delete_form=DeleteForm(),
    )


@admin_bp.route("/users/new", methods=["GET", "POST"])
@admin_required
def user_create():
    form = UserForm()
    if form.validate_on_submit():
        if User.query.filter_by(username=form.username.data).first():
            flash("Tên đăng nhập đã tồn tại.", "error")
        elif User.query.filter_by(email=form.email.data.lower()).first():
            flash("Email đã tồn tại.", "error")
        elif not form.password.data:
            flash("Cần nhập mật khẩu cho user mới.", "error")
        else:
            user = User(
                username=form.username.data.strip(),
                email=form.email.data.strip().lower(),
                role=form.role.data,
                is_active=form.is_active.data,
            )
            user.set_password(form.password.data)
            user.regenerate_api_token()
            db.session.add(user)
            db.session.commit()
            flash(f"Đã tạo user '{user.username}'.", "success")
            return redirect(url_for("admin.users"))

    return render_template("admin/user_form.html", form=form, mode="create", user=None)


@admin_bp.route("/users/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
def user_edit(user_id: int):
    user = User.query.get_or_404(user_id)
    form = UserForm(obj=user)

    if form.validate_on_submit():
        new_username = form.username.data.strip()
        new_email = form.email.data.strip().lower()
        if new_username != user.username and User.query.filter_by(username=new_username).first():
            flash("Tên đăng nhập đã tồn tại.", "error")
        elif new_email != user.email and User.query.filter_by(email=new_email).first():
            flash("Email đã tồn tại.", "error")
        else:
            user.username = new_username
            user.email = new_email
            user.role = form.role.data
            user.is_active = form.is_active.data
            if form.password.data:
                user.set_password(form.password.data)
                user.must_change_password = False
            db.session.commit()
            flash(f"Đã cập nhật user '{user.username}'.", "success")
            return redirect(url_for("admin.users"))

    return render_template("admin/user_form.html", form=form, mode="edit", user=user)


class SettingsForm(FlaskForm):
    submit = SubmitField("Lưu cấu hình")


@admin_bp.route("/settings", methods=["GET", "POST"])
@admin_required
def settings():
    form = SettingsForm()
    if form.validate_on_submit():
        # Validate + persist each known setting.
        max_workers_raw = (request.form.get("MAX_CONCURRENT_WORKERS") or "").strip()
        try:
            n = int(max_workers_raw)
            if n < 1 or n > 20:
                raise ValueError
            set_setting("MAX_CONCURRENT_WORKERS", str(n))
        except (TypeError, ValueError):
            flash("MAX_CONCURRENT_WORKERS phải là số nguyên 1-20.", "error")
            return redirect(url_for("admin.settings"))

        pages_raw = (request.form.get("DOCUMENT_AI_PAGES_PER_REQUEST") or "").strip()
        try:
            n = int(pages_raw)
            if n < 1 or n > 30:
                raise ValueError
            set_setting("DOCUMENT_AI_PAGES_PER_REQUEST", str(n))
        except (TypeError, ValueError):
            flash("DOCUMENT_AI_PAGES_PER_REQUEST phải là số nguyên 1-30.", "error")
            return redirect(url_for("admin.settings"))

        spawn = "true" if request.form.get("WORKER_SPAWN_CONSOLE") else "false"
        set_setting("WORKER_SPAWN_CONSOLE", spawn)

        flash("Đã lưu cấu hình. Worker sẽ áp dụng ở vòng polling tiếp theo.", "success")
        return redirect(url_for("admin.settings"))

    return render_template(
        "admin/settings.html",
        form=form,
        settings=list_settings(),
    )


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@admin_required
def user_delete(user_id: int):
    if user_id == current_user.id:
        flash("Không thể tự xoá tài khoản của mình.", "error")
        return redirect(url_for("admin.users"))

    form = DeleteForm()
    if not form.validate_on_submit():
        flash("CSRF không hợp lệ.", "error")
        return redirect(url_for("admin.users"))

    user = User.query.get_or_404(user_id)
    username = user.username
    db.session.delete(user)
    db.session.commit()
    flash(f"Đã xoá user '{username}'.", "success")
    return redirect(url_for("admin.users"))
