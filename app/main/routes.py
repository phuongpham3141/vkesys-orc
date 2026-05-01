"""Main UI routes: dashboard, upload, jobs, results, settings."""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from flask_login import current_user, login_required
from sqlalchemy import func
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import OCRJob, OCRResult, UserOCRConfig
from ..ocr.factory import ENGINE_LABELS, get_engine, list_engine_names
from ..services.ocr_service import get_service
from ..services.storage import (
    export_results_csv,
    export_results_json,
    export_results_markdown,
    export_results_text,
    export_results_xlsx,
    save_uploaded_pdf,
)
from .forms import SettingsForm

main_bp = Blueprint("main", __name__, template_folder="../templates/main")


@main_bp.app_context_processor
def inject_globals():
    return {
        "current_year": datetime.utcnow().year,
        "engine_labels": ENGINE_LABELS,
    }


_ENGINE_STATUS_CACHE: dict = {}
_ENGINE_STATUS_TTL_SECONDS = 60


def _engine_status_for(user) -> dict[str, dict]:
    """Return engine status (configured / not) for the given user.

    Cached for 60s per user — engine config rarely changes mid-session and
    iterating all 6 engines on every page render was a measurable hit on
    /upload, /settings and /jobs/<id>.
    """
    import time

    if not user.is_authenticated:
        cache_key = None
        config = None
    else:
        cache_key = user.id
        cached = _ENGINE_STATUS_CACHE.get(cache_key)
        if cached and (time.time() - cached["t"]) < _ENGINE_STATUS_TTL_SECONDS:
            return cached["data"]
        config = UserOCRConfig.query.filter_by(user_id=user.id).first()

    out = {}
    for name in list_engine_names():
        try:
            configured = get_engine(name).is_configured(config)
        except Exception:
            configured = False
        meta = ENGINE_LABELS.get(name, {})
        out[name] = {
            "name": name,
            "label": meta.get("label", name),
            "icon": meta.get("icon", "bi-gear"),
            "type": meta.get("type", "Local"),
            "configured": configured,
        }

    if cache_key is not None:
        _ENGINE_STATUS_CACHE[cache_key] = {"t": time.time(), "data": out}
    return out


def _invalidate_engine_status(user_id: int) -> None:
    """Drop the engine-status cache entry for a user (call after they
    edit their UserOCRConfig)."""
    _ENGINE_STATUS_CACHE.pop(user_id, None)


@main_bp.route("/")
@login_required
def dashboard():
    """Dashboard stats — collapsed from 7 separate queries to 2.

    Stats + completed-pages-sum come from one CASE-WHEN aggregation.
    by_engine uses one GROUP BY. Recent uses one ORDER BY LIMIT.
    """
    from sqlalchemy import case

    user_id = current_user.id
    base_q = OCRJob.query.filter_by(user_id=user_id)

    stats_row = db.session.query(
        func.count(OCRJob.id).label("total"),
        func.sum(case((OCRJob.status == "completed", 1), else_=0)).label("completed"),
        func.sum(
            case((OCRJob.status.in_(["pending", "processing"]), 1), else_=0)
        ).label("processing"),
        func.sum(case((OCRJob.status == "failed", 1), else_=0)).label("failed"),
        func.coalesce(
            func.sum(
                case(
                    (OCRJob.status == "completed", OCRJob.page_count),
                    else_=0,
                )
            ),
            0,
        ).label("pages"),
    ).filter(OCRJob.user_id == user_id).one()

    by_engine_rows = (
        db.session.query(OCRJob.engine, func.count(OCRJob.id))
        .filter(OCRJob.user_id == user_id)
        .group_by(OCRJob.engine)
        .all()
    )
    by_engine = [
        {
            "name": e,
            "count": c,
            "label": ENGINE_LABELS.get(e, {}).get("label", e),
        }
        for e, c in by_engine_rows
    ]

    recent = base_q.order_by(OCRJob.created_at.desc()).limit(8).all()

    return render_template(
        "main/dashboard.html",
        stats={
            "total": int(stats_row.total or 0),
            "completed": int(stats_row.completed or 0),
            "processing": int(stats_row.processing or 0),
            "failed": int(stats_row.failed or 0),
            "pages": int(stats_row.pages or 0),
        },
        by_engine=by_engine,
        recent=recent,
    )


@main_bp.route("/upload", methods=["GET"])
@login_required
def upload():
    engines = _engine_status_for(current_user)
    key_users = []
    if current_user.is_admin:
        from ..models import User as _User
        key_users = (
            _User.query.filter_by(is_active=True)
            .order_by(_User.username.asc())
            .all()
        )
    return render_template("main/upload.html", engines=engines, key_users=key_users)


@main_bp.route("/upload", methods=["POST"])
@login_required
def upload_submit():
    file = request.files.get("file")
    engine_name = (request.form.get("engine") or "").strip()

    if not file or not file.filename:
        return jsonify({"success": False, "error": {"code": "MISSING_FILE", "message": "Chưa có file"}}), 400
    if not file.filename.lower().endswith(".pdf"):
        return jsonify({"success": False, "error": {"code": "INVALID_FILE", "message": "Chỉ chấp nhận PDF"}}), 400
    if engine_name not in list_engine_names():
        return jsonify({"success": False, "error": {"code": "INVALID_ENGINE", "message": "Engine không hợp lệ"}}), 400

    stored, original, size = save_uploaded_pdf(file)

    # Admin can pick whose API keys / credentials to use for this job.
    # Regular users always use their own.
    key_user_id = None
    if current_user.is_admin:
        raw = (request.form.get("key_user_id") or "").strip()
        if raw:
            try:
                kuid = int(raw)
                if kuid != current_user.id:
                    from .. import models as _m
                    if _m.User.query.get(kuid) is not None:
                        key_user_id = kuid
            except ValueError:
                pass

    job = OCRJob(
        user_id=current_user.id,
        original_filename=original,
        stored_filename=stored,
        file_size_bytes=size,
        engine=engine_name,
        status="pending",
        source="web",
        key_user_id=key_user_id,
    )
    db.session.add(job)
    db.session.commit()

    get_service().submit_job(job.id)
    return jsonify({"success": True, "data": job.to_dict(), "error": None})


@main_bp.route("/jobs")
@login_required
def jobs():
    page = int(request.args.get("page", 1))
    per_page = 20
    status = request.args.get("status")
    engine = request.args.get("engine")

    query = OCRJob.query.filter_by(user_id=current_user.id)
    if status in {"pending", "processing", "completed", "failed"}:
        query = query.filter_by(status=status)
    if engine in list_engine_names():
        query = query.filter_by(engine=engine)
    pagination = query.order_by(OCRJob.created_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return render_template(
        "main/jobs.html",
        jobs=pagination.items,
        pagination=pagination,
        active_status=status,
        active_engine=engine,
    )


@main_bp.route("/jobs/<int:job_id>")
@login_required
def job_detail(job_id: int):
    job = OCRJob.query.get_or_404(job_id)
    if job.user_id != current_user.id and not current_user.is_admin:
        abort(403)

    # Light query: just metadata per page. Full text_content / tables are
    # lazy-loaded by the browser when the user expands an accordion item,
    # so a 90-page job no longer ships ~200KB of HTML on every nav.
    from sqlalchemy import func

    meta_rows = (
        db.session.query(
            OCRResult.page_number,
            func.char_length(OCRResult.text_content).label("text_len"),
            OCRResult.confidence_score,
        )
        .filter(OCRResult.job_id == job.id)
        .order_by(OCRResult.page_number.asc())
        .all()
    )
    results_meta = [
        {
            "page_number": r.page_number,
            "text_len": r.text_len or 0,
            "confidence": r.confidence_score,
        }
        for r in meta_rows
    ]
    engines = _engine_status_for(current_user)
    return render_template(
        "main/job_detail.html",
        job=job,
        results_meta=results_meta,
        engines=engines,
    )


@main_bp.route("/jobs/<int:job_id>/delete", methods=["POST"])
@login_required
def job_delete(job_id: int):
    job = OCRJob.query.get_or_404(job_id)
    if job.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    get_service().delete_job_artifacts(job)
    db.session.delete(job)
    db.session.commit()
    flash("Đã xoá job.", "success")
    return redirect(url_for("main.jobs"))


@main_bp.route("/jobs/<int:job_id>/retry", methods=["POST"])
@login_required
def job_retry(job_id: int):
    job = OCRJob.query.get_or_404(job_id)
    if job.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    if job.status in {"pending", "processing"}:
        flash("Job đang chạy, không thể chạy lại.", "warning")
        return redirect(url_for("main.job_detail", job_id=job.id))

    if not Path(current_app.config["UPLOAD_FOLDER"], job.stored_filename).exists():
        flash("File PDF gốc không còn — không thể chạy lại. Hãy tải lên lại.", "error")
        return redirect(url_for("main.job_detail", job_id=job.id))

    new_engine = (request.form.get("engine") or "").strip()
    engine_changed = (
        bool(new_engine)
        and new_engine in list_engine_names()
        and new_engine != job.engine
    )

    if engine_changed:
        # Different engine = different output format, so wipe old results.
        OCRResult.query.filter_by(job_id=job.id).delete(synchronize_session=False)
        job.engine = new_engine
        flash(
            f"Đã đổi engine sang '{new_engine}' và xoá kết quả cũ.", "info"
        )
    else:
        # Same engine: keep good results, drop empty / fallback ones so they
        # get reprocessed (e.g. previously crashed page or empty fallback row).
        deleted_empty = (
            OCRResult.query.filter_by(job_id=job.id)
            .filter(
                db.or_(
                    OCRResult.text_content.is_(None),
                    OCRResult.text_content == "",
                )
            )
            .delete(synchronize_session=False)
        )
        existing = (
            db.session.query(OCRResult.page_number).filter_by(job_id=job.id).count()
        )
        if deleted_empty:
            flash(
                f"Đã xoá {deleted_empty} trang rỗng/fallback để xử lý lại.",
                "info",
            )
        if existing:
            flash(
                f"Tiếp tục từ {existing} trang đã có (sẽ bỏ qua, không tính tiền lại).",
                "info",
            )

    job.target_pages = None  # full retry processes all pages
    job.status = "pending"
    job.progress_percent = 0
    job.error_message = None
    job.started_at = None
    job.completed_at = None
    db.session.commit()

    get_service().submit_job(job.id)
    flash("Đã gửi lại job vào hàng đợi OCR.", "success")
    return redirect(url_for("main.job_detail", job_id=job.id))


def _kill_pid(pid: int | None) -> bool:
    """Best-effort kill of an OCR runner subprocess by PID.

    Returns True if a kill was issued (process may already have died — that
    still counts; the caller's job-status update is what really matters).
    """
    if not pid:
        return False
    try:
        if os.name == "nt":
            import subprocess as _sp

            _sp.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                check=False,
                capture_output=True,
                timeout=5,
            )
        else:
            import signal as _sig

            os.kill(pid, _sig.SIGTERM)
        return True
    except Exception:
        return False


@main_bp.route("/jobs/<int:job_id>/stop", methods=["POST"])
@login_required
def job_stop(job_id: int):
    job = OCRJob.query.get_or_404(job_id)
    if job.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    if job.status not in {"pending", "processing"}:
        flash("Job đã dừng / hoàn tất từ trước.", "info")
        return redirect(url_for("main.job_detail", job_id=job.id))

    pid = job.runner_pid
    killed = _kill_pid(pid)
    job.status = "failed"
    job.error_message = (
        f"Đã dừng bởi user (PID {pid})" if pid else "Đã dừng bởi user (chưa kịp spawn)"
    )
    job.runner_pid = None
    job.completed_at = datetime.utcnow()
    db.session.commit()

    if pid and killed:
        flash(f"Đã gửi tín hiệu dừng tới process {pid}.", "success")
    else:
        flash("Đã đánh dấu job là dừng.", "success")
    return redirect(url_for("main.job_detail", job_id=job.id))


@main_bp.route("/jobs/stop-all", methods=["POST"])
@login_required
def jobs_stop_all():
    base_q = OCRJob.query.filter(OCRJob.status.in_(["pending", "processing"]))
    if not current_user.is_admin:
        base_q = base_q.filter_by(user_id=current_user.id)

    pids: list[int] = []
    count = 0
    for job in base_q.all():
        if job.runner_pid:
            pids.append(job.runner_pid)
        job.status = "failed"
        job.error_message = "Đã dừng bởi user (Stop all)"
        job.runner_pid = None
        job.completed_at = datetime.utcnow()
        count += 1
    db.session.commit()

    killed = 0
    for pid in pids:
        if _kill_pid(pid):
            killed += 1

    if count == 0:
        flash("Không có job nào đang chạy.", "info")
    else:
        flash(
            f"Đã dừng {count} job ({killed} subprocess đã kill).",
            "success",
        )
    return redirect(url_for("main.jobs"))


@main_bp.route("/jobs/<int:job_id>/test-page", methods=["POST"])
@login_required
def job_test_page(job_id: int):
    """Run OCR for a single chosen page only.

    Cheap way to verify the engine + credentials before running the whole
    document: deletes any existing result for that page, sets
    ``OCRJob.target_pages = [page]``, and resubmits. The worker honours
    target_pages and skips every other page in the PDF.
    """
    job = OCRJob.query.get_or_404(job_id)
    if job.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    if job.status in {"pending", "processing"}:
        flash("Job đang chạy, không thể test.", "warning")
        return redirect(url_for("main.job_detail", job_id=job.id))

    try:
        page_number = int(request.form.get("page_number", 1))
    except (TypeError, ValueError):
        page_number = 1
    if page_number < 1:
        page_number = 1
    if job.page_count and page_number > job.page_count:
        flash(
            f"Trang {page_number} vượt quá số trang ({job.page_count}).",
            "error",
        )
        return redirect(url_for("main.job_detail", job_id=job.id))

    if not Path(current_app.config["UPLOAD_FOLDER"], job.stored_filename).exists():
        flash("File PDF gốc không còn — không thể test.", "error")
        return redirect(url_for("main.job_detail", job_id=job.id))

    # Drop old fallback / empty rows (e.g. "Trang không có văn bản" from a
    # previous failed run) so the user doesn't keep seeing them at the top
    # of the job detail accordion after a successful test.
    OCRResult.query.filter_by(job_id=job.id).filter(
        db.or_(
            OCRResult.text_content.is_(None),
            OCRResult.text_content == "",
        )
    ).delete(synchronize_session=False)
    OCRResult.query.filter_by(job_id=job.id, page_number=page_number).delete(
        synchronize_session=False
    )

    job.target_pages = [page_number]
    job.status = "pending"
    job.progress_percent = 0
    job.error_message = None
    job.started_at = None
    job.completed_at = None
    db.session.commit()

    get_service().submit_job(job.id)
    flash(
        f"Đã gửi test trang {page_number}. Worker sẽ chỉ chạy 1 trang này (rẻ + nhanh).",
        "success",
    )
    return redirect(url_for("main.job_detail", job_id=job.id))


@main_bp.route("/jobs/<int:job_id>/download/<string:fmt>")
@login_required
def job_download(job_id: int, fmt: str):
    job = OCRJob.query.get_or_404(job_id)
    if job.user_id != current_user.id and not current_user.is_admin:
        abort(403)
    if job.status != "completed":
        flash("Job chưa hoàn tất.", "warning")
        return redirect(url_for("main.job_detail", job_id=job.id))

    results = job.results.order_by(OCRResult.page_number.asc()).all()
    fmt = fmt.lower()
    if fmt == "txt":
        path = export_results_text(job, results)
    elif fmt == "json":
        path = export_results_json(job, results)
    elif fmt in {"md", "markdown"}:
        path = export_results_markdown(job, results)
    elif fmt == "csv":
        path = export_results_csv(job, results)
    elif fmt in {"xlsx", "excel"}:
        path = export_results_xlsx(job, results)
    else:
        abort(400)

    download_name = f"{Path(job.original_filename).stem}.{path.suffix.lstrip('.')}"
    return send_file(str(path), as_attachment=True, download_name=download_name)


@main_bp.route("/settings/gemini/models", methods=["POST"])
@login_required
def gemini_models():
    """Return the list of Gemini models available to the caller's API key.

    Looks up the key in this priority:
      1. form ``api_key`` field (a key the user typed but hasn't saved yet)
      2. encrypted ``UserOCRConfig.gemini_api_key`` for the current user
      3. ``GEMINI_API_KEY`` env fallback
    """
    config = UserOCRConfig.query.filter_by(user_id=current_user.id).first()
    api_key = (request.form.get("api_key") or "").strip()
    if not api_key and config is not None:
        api_key = config.gemini_api_key or ""
    if not api_key:
        api_key = current_app.config.get("GEMINI_API_KEY") or ""
    if not api_key:
        return (
            jsonify(
                {
                    "success": False,
                    "error": {
                        "code": "MISSING_KEY",
                        "message": "Cần Gemini API key (gõ vào ô bên trái rồi bấm lại, hoặc lưu key trước).",
                    },
                }
            ),
            400,
        )

    try:
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        models = []
        for m in genai.list_models():
            methods = list(getattr(m, "supported_generation_methods", []) or [])
            if "generateContent" not in methods:
                continue
            raw_name = getattr(m, "name", "") or ""
            name = raw_name.split("/", 1)[1] if "/" in raw_name else raw_name
            if not name:
                continue
            models.append(
                {
                    "name": name,
                    "display_name": getattr(m, "display_name", "") or name,
                    "description": (getattr(m, "description", "") or "")[:200],
                    "input_token_limit": getattr(m, "input_token_limit", 0),
                }
            )

        def _sort_key(m: dict) -> tuple:
            n = m["name"]
            return (
                not n.startswith("gemini"),
                "pro" not in n,
                "flash" not in n,
                "preview" in n or "exp" in n,
                "lite" in n,
                n,
            )

        models.sort(key=_sort_key)
        return jsonify({"success": True, "data": models, "error": None})
    except Exception as exc:
        return (
            jsonify(
                {
                    "success": False,
                    "error": {
                        "code": "GEMINI_API_ERROR",
                        "message": f"Không thể lấy danh sách model: {exc}",
                    },
                }
            ),
            500,
        )


@main_bp.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    config = UserOCRConfig.query.filter_by(user_id=current_user.id).first()
    if config is None:
        config = UserOCRConfig(user_id=current_user.id)
        db.session.add(config)
        db.session.commit()

    form = SettingsForm(
        google_credentials_path=config.google_credentials_path or "",
        tesseract_cmd_path=config.tesseract_cmd_path or "",
        documentai_project_id=config.documentai_project_id or "",
        documentai_location=config.documentai_location or "",
        documentai_processor_id=config.documentai_processor_id or "",
        gemini_model=config.gemini_model or "",
    )

    if form.validate_on_submit():
        if form.google_credentials_file.data:
            uploaded = form.google_credentials_file.data
            cred_dir = Path(current_app.root_path).parent / "credentials"
            cred_dir.mkdir(parents=True, exist_ok=True)
            safe = secure_filename(uploaded.filename or "google.json")
            target = cred_dir / f"user{current_user.id}_{uuid.uuid4().hex[:8]}_{safe}"
            uploaded.save(str(target))
            config.google_credentials_path = str(target)
        elif form.google_credentials_path.data:
            config.google_credentials_path = form.google_credentials_path.data.strip() or None
        else:
            config.google_credentials_path = None

        if form.mistral_api_key.data:
            config.mistral_api_key = form.mistral_api_key.data.strip()
        if form.gemini_api_key.data:
            config.gemini_api_key = form.gemini_api_key.data.strip()
        config.tesseract_cmd_path = form.tesseract_cmd_path.data.strip() or None
        config.documentai_project_id = form.documentai_project_id.data.strip() or None
        config.documentai_location = form.documentai_location.data.strip() or None
        config.documentai_processor_id = form.documentai_processor_id.data.strip() or None
        config.gemini_model = form.gemini_model.data.strip() or None

        db.session.commit()
        _invalidate_engine_status(current_user.id)
        flash("Đã lưu cấu hình.", "success")
        return redirect(url_for("main.settings"))

    engines = _engine_status_for(current_user)
    return render_template("main/settings.html", form=form, engines=engines, config=config)
