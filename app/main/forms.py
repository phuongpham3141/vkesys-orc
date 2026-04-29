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

    # Document AI
    documentai_project_id = StringField(
        "GCP Project ID",
        validators=[Optional(), Length(max=128)],
    )
    documentai_location = StringField(
        "Location (us / eu / ...)",
        validators=[Optional(), Length(max=32)],
    )
    documentai_processor_id = StringField(
        "Processor ID (Layout Parser)",
        validators=[Optional(), Length(max=128)],
    )

    # Gemini
    gemini_api_key = PasswordField(
        "Gemini API Key",
        validators=[Optional(), Length(max=512)],
    )
    gemini_model = StringField(
        "Gemini model (mặc định: gemini-2.5-pro)",
        validators=[Optional(), Length(max=64)],
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
