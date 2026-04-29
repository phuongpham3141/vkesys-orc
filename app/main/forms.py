"""Main blueprint forms (settings, etc.)."""
from __future__ import annotations

from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import Length, Optional


class SettingsForm(FlaskForm):
    google_credentials_path = StringField(
        "Đường dẫn Google service account JSON",
        validators=[Optional(), Length(max=512)],
    )
    google_credentials_file = FileField(
        "...hoặc tải lên file JSON",
        validators=[Optional(), FileAllowed(["json"], "Chỉ chấp nhận file .json")],
    )
    mistral_api_key = PasswordField(
        "Mistral API Key",
        validators=[Optional(), Length(max=512)],
    )
    tesseract_cmd_path = StringField(
        "Đường dẫn tesseract.exe",
        validators=[Optional(), Length(max=512)],
    )
    submit = SubmitField("Lưu cấu hình")
