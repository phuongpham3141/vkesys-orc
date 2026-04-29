"""Auth-related Flask-WTF forms."""
from __future__ import annotations

from flask_wtf import FlaskForm
from wtforms import BooleanField, PasswordField, StringField, SubmitField
from wtforms.validators import (
    DataRequired,
    Email,
    EqualTo,
    Length,
    Optional,
    Regexp,
    ValidationError,
)


class LoginForm(FlaskForm):
    identity = StringField(
        "Tên đăng nhập hoặc Email",
        validators=[DataRequired(), Length(max=255)],
    )
    password = PasswordField("Mật khẩu", validators=[DataRequired()])
    remember = BooleanField("Ghi nhớ đăng nhập")
    submit = SubmitField("Đăng nhập")


class RegisterForm(FlaskForm):
    username = StringField(
        "Tên đăng nhập",
        validators=[
            DataRequired(),
            Length(min=3, max=64),
            Regexp(r"^[A-Za-z0-9_.-]+$", message="Chỉ chữ, số, _ . -"),
        ],
    )
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    password = PasswordField(
        "Mật khẩu",
        validators=[DataRequired(), Length(min=8, message="Tối thiểu 8 ký tự")],
    )
    password_confirm = PasswordField(
        "Nhập lại mật khẩu",
        validators=[DataRequired(), EqualTo("password", message="Mật khẩu không khớp")],
    )
    submit = SubmitField("Đăng ký")

    def validate_username(self, field) -> None:  # type: ignore[no-untyped-def]
        from ..models import User

        if User.query.filter_by(username=field.data).first():
            raise ValidationError("Tên đăng nhập đã tồn tại")

    def validate_email(self, field) -> None:  # type: ignore[no-untyped-def]
        from ..models import User

        if User.query.filter_by(email=field.data.lower()).first():
            raise ValidationError("Email đã tồn tại")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Mật khẩu hiện tại", validators=[DataRequired()])
    new_password = PasswordField(
        "Mật khẩu mới",
        validators=[DataRequired(), Length(min=8, message="Tối thiểu 8 ký tự")],
    )
    new_password_confirm = PasswordField(
        "Nhập lại mật khẩu mới",
        validators=[DataRequired(), EqualTo("new_password", message="Mật khẩu không khớp")],
    )
    submit = SubmitField("Đổi mật khẩu")


class RegenerateTokenForm(FlaskForm):
    submit = SubmitField("Tạo lại API token")


class UpdateProfileForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired(), Email(), Length(max=255)])
    submit = SubmitField("Cập nhật")
