"""Admin user management routes."""
from __future__ import annotations

from functools import wraps

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for
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


class TestSpawnForm(FlaskForm):
    submit = SubmitField("Test spawn console")


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
        test_form=TestSpawnForm(),
        settings=list_settings(
            keys=[
                "MAX_CONCURRENT_WORKERS",
                "DOCUMENT_AI_PAGES_PER_REQUEST",
                "WORKER_SPAWN_CONSOLE",
                "LAST_SCHEDULER_HEARTBEAT",
                "LAST_SCHEDULER_PID",
            ]
        ),
    )


@admin_bp.route("/system-status")
@admin_required
def system_status():
    """Render the live system status dashboard (admin only)."""
    return render_template("admin/system_status.html")


@admin_bp.route("/system-status/data")
@admin_required
def system_status_data():
    """JSON snapshot of every health signal the dashboard renders."""
    import os
    import socket
    import time
    from datetime import datetime, timedelta
    from pathlib import Path

    from flask import jsonify
    from sqlalchemy import func, text

    from ..extensions import db as _db
    from ..models import OCRJob, OCRResult, Setting

    project_root = Path(current_app.root_path).parent

    # --- Flask web ---
    flask_health = {
        "alive": True,  # we're serving this very request
        "host": socket.gethostname(),
        "port": int(os.getenv("FLASK_PORT", "8000")),
    }

    # --- Scheduler heartbeat (settings table) ---
    sched = {"alive": False, "age_seconds": None, "pid": None, "value": None}
    hb = _db.session.get(Setting, "LAST_SCHEDULER_HEARTBEAT")
    pid_row = _db.session.get(Setting, "LAST_SCHEDULER_PID")
    if hb is not None and hb.updated_at is not None:
        age_s = max(0, int((datetime.utcnow() - hb.updated_at).total_seconds()))
        sched["age_seconds"] = age_s
        sched["alive"] = age_s < 300  # < 5 min = healthy
        sched["value"] = hb.value
    if pid_row is not None and pid_row.value:
        try:
            sched["pid"] = int(pid_row.value)
        except (TypeError, ValueError):
            pass

    # --- Live worker subprocess count ---
    workers_alive = 0
    workers_pids: list[dict] = []
    try:
        import psutil

        if sched["pid"] and psutil.pid_exists(sched["pid"]):
            sched["alive_pid"] = True
        else:
            sched["alive_pid"] = False

        # Find processes related to OCR runner
        for p in psutil.process_iter(attrs=["pid", "name", "cmdline", "create_time"]):
            try:
                cmdline = p.info.get("cmdline") or []
                cmdstr = " ".join(cmdline)
                if "run_one_job.py" in cmdstr:
                    workers_alive += 1
                    workers_pids.append(
                        {
                            "pid": p.info["pid"],
                            "started": int(p.info["create_time"]),
                            "runtime_s": int(time.time() - p.info["create_time"]),
                        }
                    )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except ImportError:
        sched["alive_pid"] = None

    # --- Job queue stats ---
    queue = {}
    counts = (
        _db.session.query(OCRJob.status, func.count(OCRJob.id))
        .group_by(OCRJob.status)
        .all()
    )
    queue["by_status"] = {status: int(count) for status, count in counts}
    last_24h = datetime.utcnow() - timedelta(hours=24)
    queue["completed_24h"] = (
        _db.session.query(func.count(OCRJob.id))
        .filter(OCRJob.status == "completed", OCRJob.completed_at >= last_24h)
        .scalar()
        or 0
    )
    queue["failed_24h"] = (
        _db.session.query(func.count(OCRJob.id))
        .filter(OCRJob.status == "failed", OCRJob.completed_at >= last_24h)
        .scalar()
        or 0
    )
    queue["pages_24h"] = int(
        _db.session.query(func.coalesce(func.sum(OCRJob.page_count), 0))
        .filter(OCRJob.status == "completed", OCRJob.completed_at >= last_24h)
        .scalar()
        or 0
    )
    # Oldest pending — if more than a few minutes old, scheduler probably stuck
    oldest_pending = (
        _db.session.query(OCRJob.created_at)
        .filter(OCRJob.status == "pending")
        .order_by(OCRJob.created_at.asc())
        .first()
    )
    if oldest_pending and oldest_pending[0]:
        queue["oldest_pending_age_s"] = max(
            0, int((datetime.utcnow() - oldest_pending[0]).total_seconds())
        )
    else:
        queue["oldest_pending_age_s"] = None

    # --- PostgreSQL stats ---
    pg = {}
    try:
        rows = _db.session.execute(
            text(
                "SELECT count(*)::int AS active, "
                "(SELECT setting::int FROM pg_settings WHERE name='max_connections') AS limit_ "
                "FROM pg_stat_activity WHERE datname=current_database()"
            )
        ).fetchone()
        pg["connections_active"] = int(rows[0])
        pg["connections_max"] = int(rows[1])
        size_row = _db.session.execute(
            text("SELECT pg_size_pretty(pg_database_size(current_database()))")
        ).scalar()
        pg["db_size"] = size_row
    except Exception as exc:
        pg["error"] = str(exc)[:200]

    # --- Disk usage ---
    def _dir_size(p: Path) -> int:
        if not p.exists():
            return 0
        total = 0
        try:
            for f in p.rglob("*"):
                if f.is_file():
                    try:
                        total += f.stat().st_size
                    except OSError:
                        pass
        except OSError:
            pass
        return total

    def _human(n: int) -> str:
        for u in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.1f} {u}" if u != "B" else f"{n} B"
            n /= 1024
        return f"{n:.1f} TB"

    disk = {
        "uploads": _human(_dir_size(project_root / "uploads")),
        "outputs": _human(_dir_size(project_root / "outputs")),
        "logs": _human(_dir_size(project_root / "logs")),
    }

    # --- Recent log tails ---
    def _tail(path: Path, lines: int = 12) -> list[str]:
        if not path.exists():
            return []
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as fh:
                return fh.readlines()[-lines:]
        except OSError:
            return []

    logs = {
        "scheduler": [l.rstrip() for l in _tail(project_root / "logs" / "scheduler.log", 10)],
        "health": [l.rstrip() for l in _tail(project_root / "logs" / "health.log", 10)],
        "app_slow": [
            l.rstrip()
            for l in _tail(project_root / "logs" / "app.log", 200)
            if "SLOW" in l
        ][-5:],
    }

    # --- Watchdog last run from health.log ---
    watchdog = {"last_run": None, "last_status": None}
    if logs["health"]:
        for line in reversed(logs["health"]):
            if "Health check start" in line:
                watchdog["last_run"] = line[1:20] if line.startswith("[") else line[:20]
                break
        watchdog["last_status"] = "OK" if any(
            "OK" in l and "Flask" in l for l in logs["health"][-5:]
        ) else "STALE"

    return jsonify(
        {
            "ts": int(time.time()),
            "flask": flask_health,
            "scheduler": sched,
            "workers": {"alive": workers_alive, "pids": workers_pids},
            "queue": queue,
            "pg": pg,
            "disk": disk,
            "logs": logs,
            "watchdog": watchdog,
        }
    )


@admin_bp.route("/system-status/run-health-check", methods=["POST"])
@admin_required
def system_status_run_health_check():
    """Trigger watchdog health_check.py immediately. Returns OK/error."""
    import subprocess
    from pathlib import Path
    from flask import jsonify

    form = TestSpawnForm()
    if not form.validate_on_submit():
        return jsonify({"success": False, "error": "Invalid CSRF"}), 400

    project_root = Path(current_app.root_path).parent
    pythonw = project_root / "venv" / "Scripts" / "pythonw.exe"
    py = project_root / "venv" / "Scripts" / "python.exe"
    exe = pythonw if pythonw.exists() else py
    script = project_root / "scripts" / "health_check.py"
    if not exe.exists() or not script.exists():
        return jsonify({"success": False, "error": "health_check.py not found"}), 500
    try:
        subprocess.Popen(
            [str(exe), str(script)],
            cwd=str(project_root),
            creationflags=0x00000008,  # DETACHED_PROCESS
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return jsonify({"success": True})
    except Exception as exc:
        return jsonify({"success": False, "error": str(exc)[:200]}), 500


@admin_bp.route("/settings/test-spawn", methods=["POST"])
@admin_required
def settings_test_spawn():
    """Spawn a tiny test subprocess in a new console to verify the
    Windows ``CREATE_NEW_CONSOLE`` mechanism works from this process."""
    import os as _os
    import subprocess as _sp
    import sys as _sys

    form = TestSpawnForm()
    if not form.validate_on_submit():
        flash("CSRF không hợp lệ.", "error")
        return redirect(url_for("admin.settings"))

    code = (
        "import time, os, sys; "
        "print('=== VIC OCR spawn test (pid=' + str(os.getpid()) + ') ==='); "
        "print('Python:', sys.executable); "
        "print('Cua so se tu dong dong sau 15s'); "
        "[print(f'tick {i+1}/15') or time.sleep(1) for i in range(15)]"
    )
    cmd = [_sys.executable, "-c", code]
    flags = _sp.CREATE_NEW_CONSOLE if _os.name == "nt" else 0  # type: ignore[attr-defined]
    try:
        proc = _sp.Popen(cmd, creationflags=flags)
        flash(
            f"Spawn thành công (pid={proc.pid}). Cửa sổ Python test sẽ hiện ngay — "
            f"nếu bạn KHÔNG thấy nó, tức là cơ chế CREATE_NEW_CONSOLE bị block.",
            "success",
        )
    except Exception as exc:
        flash(f"Spawn thất bại: {exc}", "error")
    return redirect(url_for("admin.settings"))


@admin_bp.route("/users/<int:user_id>/toggle-active", methods=["POST"])
@admin_required
def user_toggle_active(user_id: int):
    """Quick enable/disable a user account without going through the full edit form."""
    if user_id == current_user.id:
        flash("Không thể tự khoá tài khoản của chính mình.", "error")
        return redirect(url_for("admin.users"))

    form = DeleteForm()
    if not form.validate_on_submit():
        flash("CSRF không hợp lệ.", "error")
        return redirect(url_for("admin.users"))

    user = User.query.get_or_404(user_id)
    user.is_active = not user.is_active
    db.session.commit()
    state = "kích hoạt" if user.is_active else "khoá"
    flash(f"Đã {state} tài khoản '{user.username}'.", "success")
    return redirect(url_for("admin.users"))


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
