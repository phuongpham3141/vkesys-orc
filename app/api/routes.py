"""REST API endpoints (token-authenticated, rate-limited)."""
from __future__ import annotations

from flask import Blueprint, current_app, request
from flask_login import current_user

from ..extensions import db, limiter
from ..models import OCRJob, OCRResult, UserOCRConfig
from ..ocr.factory import ENGINE_LABELS, get_engine, list_engine_names
from ..services.ocr_service import get_service
from ..services.storage import save_uploaded_pdf
from .auth import get_api_user, token_required
from .responses import api_error, api_success

api_bp = Blueprint("api", __name__)


@api_bp.before_request
def _apply_rate_limit():
    """Apply API_RATE_LIMIT configured in env to all API routes."""
    pass  # decorator-based limiter applied per route below


def _serialize_job(job: OCRJob) -> dict:
    return job.to_dict()


def _serialize_result(r: OCRResult) -> dict:
    return r.to_dict()


@api_bp.route("/engines", methods=["GET"])
@token_required
def engines():
    user = get_api_user()
    config = UserOCRConfig.query.filter_by(user_id=user.id).first()
    out = []
    for name in list_engine_names():
        try:
            configured = get_engine(name).is_configured(config)
        except Exception:
            configured = False
        meta = ENGINE_LABELS.get(name, {})
        out.append(
            {
                "name": name,
                "label": meta.get("label", name),
                "type": meta.get("type", "Local"),
                "configured": configured,
            }
        )
    return api_success(data=out)


@api_bp.route("/ocr", methods=["POST"])
@token_required
@limiter.limit(lambda: current_app.config.get("API_RATE_LIMIT", "60/minute"))
def submit_ocr():
    user = get_api_user()
    file = request.files.get("file")
    engine_name = (request.form.get("engine") or "").strip()

    if not file or not file.filename:
        return api_error("MISSING_FILE", "Field 'file' is required", 400)
    if not file.filename.lower().endswith(".pdf"):
        return api_error("INVALID_FILE", "Only PDF files are accepted", 400)
    if engine_name not in list_engine_names():
        return api_error(
            "INVALID_ENGINE",
            f"Engine must be one of {list_engine_names()}",
            400,
        )

    stored, original, size = save_uploaded_pdf(file)

    job = OCRJob(
        user_id=user.id,
        original_filename=original,
        stored_filename=stored,
        file_size_bytes=size,
        engine=engine_name,
        status="pending",
        source="api",
    )
    db.session.add(job)
    db.session.commit()
    get_service().submit_job(job.id)

    return api_success(data=_serialize_job(job), status=201)


@api_bp.route("/jobs", methods=["GET"])
@token_required
@limiter.limit(lambda: current_app.config.get("API_RATE_LIMIT", "60/minute"))
def list_jobs():
    user = get_api_user()
    status = request.args.get("status")
    engine = request.args.get("engine")
    limit = min(int(request.args.get("limit", 50)), 200)
    offset = max(int(request.args.get("offset", 0)), 0)

    query = OCRJob.query.filter_by(user_id=user.id)
    if status in {"pending", "processing", "completed", "failed"}:
        query = query.filter_by(status=status)
    if engine in list_engine_names():
        query = query.filter_by(engine=engine)

    total = query.count()
    items = query.order_by(OCRJob.created_at.desc()).offset(offset).limit(limit).all()
    return api_success(
        data=[_serialize_job(j) for j in items],
        meta={"total": total, "limit": limit, "offset": offset},
    )


@api_bp.route("/jobs/<int:job_id>", methods=["GET"])
@token_required
@limiter.limit(lambda: current_app.config.get("API_RATE_LIMIT", "60/minute"))
def get_job(job_id: int):
    user = get_api_user()
    job = OCRJob.query.get(job_id)
    if job is None:
        return api_error("NOT_FOUND", "Job not found", 404)
    if job.user_id != user.id and not user.is_admin:
        return api_error("FORBIDDEN", "Not allowed", 403)
    return api_success(data=_serialize_job(job))


@api_bp.route("/jobs/<int:job_id>/results", methods=["GET"])
@token_required
@limiter.limit(lambda: current_app.config.get("API_RATE_LIMIT", "60/minute"))
def get_job_results(job_id: int):
    user = get_api_user()
    job = OCRJob.query.get(job_id)
    if job is None:
        return api_error("NOT_FOUND", "Job not found", 404)
    if job.user_id != user.id and not user.is_admin:
        return api_error("FORBIDDEN", "Not allowed", 403)

    fmt = (request.args.get("format") or "json").lower()
    results = job.results.order_by(OCRResult.page_number.asc()).all()

    if fmt == "text":
        text = "\n\n".join(f"===== Trang {r.page_number} =====\n{r.text_content}" for r in results)
        return api_success(data={"text": text})
    if fmt == "markdown":
        md = f"# {job.original_filename}\n\n"
        for r in results:
            md += f"\n## Trang {r.page_number}\n\n{r.text_content}\n"
        return api_success(data={"markdown": md})
    return api_success(
        data={
            "job": _serialize_job(job),
            "pages": [_serialize_result(r) for r in results],
        }
    )


@api_bp.route("/jobs/<int:job_id>/results/<int:page>", methods=["GET"])
@token_required
@limiter.limit(lambda: current_app.config.get("API_RATE_LIMIT", "60/minute"))
def get_job_page(job_id: int, page: int):
    user = get_api_user()
    job = OCRJob.query.get(job_id)
    if job is None:
        return api_error("NOT_FOUND", "Job not found", 404)
    if job.user_id != user.id and not user.is_admin:
        return api_error("FORBIDDEN", "Not allowed", 403)

    result = job.results.filter_by(page_number=page).first()
    if result is None:
        return api_error("PAGE_NOT_FOUND", f"Page {page} not found", 404)
    return api_success(data=_serialize_result(result))


@api_bp.route("/jobs/<int:job_id>", methods=["DELETE"])
@token_required
@limiter.limit(lambda: current_app.config.get("API_RATE_LIMIT", "60/minute"))
def delete_job(job_id: int):
    user = get_api_user()
    job = OCRJob.query.get(job_id)
    if job is None:
        return api_error("NOT_FOUND", "Job not found", 404)
    if job.user_id != user.id and not user.is_admin:
        return api_error("FORBIDDEN", "Not allowed", 403)

    get_service().delete_job_artifacts(job)
    db.session.delete(job)
    db.session.commit()
    return api_success(data={"deleted": True, "id": job_id})


@api_bp.route("/jobs/<int:job_id>/public", methods=["GET"])
def get_job_public(job_id: int):
    """Session-authenticated lightweight status endpoint used by the UI poller."""
    if not current_user.is_authenticated:
        return api_error("UNAUTHORIZED", "Login required", 401)
    job = OCRJob.query.get(job_id)
    if job is None:
        return api_error("NOT_FOUND", "Job not found", 404)
    if job.user_id != current_user.id and not current_user.is_admin:
        return api_error("FORBIDDEN", "Not allowed", 403)
    return api_success(
        data={
            "id": job.id,
            "status": job.status,
            "progress_percent": job.progress_percent,
            "page_count": job.page_count,
            "error_message": job.error_message,
        }
    )
