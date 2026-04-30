# VIC OCR — Flask Multi-Engine OCR Platform

> **🚨 Cho Claude Code session sau (2026-04-28+)**:
> Project ĐÃ ĐƯỢC BUILD theo spec dưới đây.
> **Đọc [`docs/HANDOFF.md`](docs/HANDOFF.md) TRƯỚC** để biết:
> - Trạng thái hiện tại (21 commit, đã verify Document AI Layout với Vingroup PDF)
> - Kiến trúc (2 process: Flask + scheduler, mỗi job 1 cửa sổ Python console)
> - Roadmap tích hợp ESG scoring (mục 10 trong HANDOFF.md)
> - Debugging recipes
>
> File này (`Claude.md`) là spec gốc — KHÔNG còn là lệnh build, mà là tham chiếu lịch sử.
> Code thực tế có thể đã evolve khác spec một số chỗ (ví dụ: 6 engines thay vì 4, page_number atomic save, etc).

> **Hướng dẫn cho Claude Code (build lần đầu)**: File này mô tả đầy đủ yêu cầu xây dựng ứng dụng. Đọc kỹ toàn bộ trước khi bắt đầu code. Implement theo đúng cấu trúc, không tự ý đổi tên file/folder hoặc bỏ qua tính năng.

---

## 1. Project Overview

A Flask web application that performs OCR on PDF files (especially Vietnamese financial reports / scanned documents) using **four OCR engines**, with full user management, REST API, and batch folder processing. Results are stored in PostgreSQL for full-text search and later analysis.

### Primary use case
- Input: scanned PDFs (e.g., Vietnamese financial statements like Vingroup annual reports — 90-216 pages, ~10-15 MB each)
- Process: OCR via user-selected engine
- Output: extracted text + structured table data stored in PostgreSQL, exportable as TXT/JSON

### Three input methods (all required)
1. **Web UI** — drag-and-drop file upload through browser
2. **REST API** — programmatic upload (`POST /api/v1/ocr`)
3. **Folder watch** — scan a configured folder, OCR all PDFs found, optionally move to processed folder

---

## 2. Tech Stack

| Layer | Technology | Version |
|---|---|---|
| Backend | Python + Flask | Python 3.11+, Flask 3.x |
| ORM | SQLAlchemy + Flask-SQLAlchemy | latest |
| Migrations | Flask-Migrate (Alembic) | latest |
| Auth | Flask-Login + Flask-WTF | latest |
| Password hash | werkzeug.security (pbkdf2:sha256) | built-in |
| Database | PostgreSQL | 16+ (already installed) |
| DB driver | psycopg[binary] (psycopg3) | latest |
| Frontend CSS | Bootstrap | **5.3.x (latest)** via CDN |
| Frontend theme | Galaxy UI aesthetic — dark space theme, custom CSS | custom |
| Icons | Bootstrap Icons | latest |
| Async tasks | `concurrent.futures.ThreadPoolExecutor` (no Celery — keep simple) | built-in |
| Config | python-dotenv (.env file) | latest |

### OCR Engines (all four required)

| Engine | Package | Type | Notes |
|---|---|---|---|
| Google Cloud Vision | `google-cloud-vision` | Cloud API | Free tier 1,000 pages/month — needs service account JSON |
| Mistral OCR | `mistralai` | Cloud API | ~$1 per 1,000 pages — needs API key |
| PaddleOCR | `paddleocr` + `paddlepaddle` | Local | Heavy install (~2GB), supports Vietnamese, has built-in table detection |
| Tesseract | `pytesseract` + Tesseract binary | Local | User must install Tesseract separately + Vietnamese language data |

PDF → image conversion: use `pdf2image` (requires Poppler binaries on Windows — document this in README).

---

## 3. Project Structure

Create exactly this structure:

```
vic_ocr/
├── app/
│   ├── __init__.py              # Flask app factory
│   ├── models.py                # SQLAlchemy models
│   ├── extensions.py            # db, login_manager, migrate instances
│   ├── config.py                # Config classes (Dev, Prod)
│   │
│   ├── auth/                    # Authentication blueprint
│   │   ├── __init__.py
│   │   ├── routes.py            # login, logout, register, profile
│   │   └── forms.py             # Flask-WTF forms
│   │
│   ├── main/                    # Main UI blueprint
│   │   ├── __init__.py
│   │   ├── routes.py            # dashboard, upload page, jobs list, results viewer
│   │   └── forms.py
│   │
│   ├── admin/                   # Admin user management
│   │   ├── __init__.py
│   │   └── routes.py            # list users, create, edit, delete, change role
│   │
│   ├── api/                     # REST API blueprint
│   │   ├── __init__.py
│   │   ├── routes.py            # /api/v1/ocr, /api/v1/jobs/<id>, etc.
│   │   └── auth.py              # API token authentication
│   │
│   ├── ocr/                     # OCR engine adapters
│   │   ├── __init__.py
│   │   ├── base.py              # Abstract base class OCREngine
│   │   ├── google_vision.py     # GoogleVisionOCR
│   │   ├── mistral.py           # MistralOCR
│   │   ├── paddle.py            # PaddleOCR adapter
│   │   ├── tesseract.py         # TesseractOCR
│   │   ├── factory.py           # get_engine(name) -> OCREngine
│   │   └── pdf_utils.py         # PDF→images, page splitting
│   │
│   ├── services/
│   │   ├── __init__.py
│   │   ├── ocr_service.py       # Main OCR orchestrator (uses ThreadPoolExecutor)
│   │   ├── folder_watcher.py    # Background folder scanning
│   │   └── storage.py           # File save/load helpers
│   │
│   ├── static/
│   │   ├── css/
│   │   │   └── galaxy.css       # Galaxy UI theme overrides
│   │   ├── js/
│   │   │   ├── app.js
│   │   │   └── upload.js        # Drag-drop + progress polling
│   │   └── img/
│   │       └── stars-bg.svg     # Decorative background
│   │
│   └── templates/
│       ├── base.html            # Base layout with Galaxy UI
│       ├── auth/
│       │   ├── login.html
│       │   ├── register.html
│       │   └── profile.html
│       ├── main/
│       │   ├── dashboard.html
│       │   ├── upload.html
│       │   ├── jobs.html        # Job list with status
│       │   ├── job_detail.html  # View results, download
│       │   └── settings.html    # API keys management per user
│       ├── admin/
│       │   ├── users.html
│       │   └── user_form.html
│       └── errors/
│           ├── 404.html
│           └── 500.html
│
├── migrations/                  # Alembic auto-generated
├── uploads/                     # User-uploaded PDFs (gitignored)
├── outputs/                     # OCR result exports (gitignored)
├── watch_folder/                # Folder watcher input (gitignored)
├── watch_folder_processed/      # After processing (gitignored)
├── credentials/                 # Google service account JSON (gitignored)
│
├── .env.example                 # Template, committed
├── .env                         # Real secrets, gitignored
├── .gitignore
├── requirements.txt
├── run.py                       # Entry point: `python run.py`
├── wsgi.py                      # For production deployment
├── README.md                    # Setup instructions in Vietnamese + English
└── CLAUDE.md                    # This file
```

---

## 4. Database Schema

PostgreSQL connection (already configured by user):
- Host: `localhost`
- Port: `5432`
- User: `postgres`
- Password: `Phuong2606`
- Database: `vic_ocr` (create this)

Enable extensions on first migration:
```sql
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

### Models (app/models.py)

```python
# User
class User:
    id: int (PK)
    username: str (unique, indexed)
    email: str (unique, indexed)
    password_hash: str
    role: str  # 'admin' or 'user'
    api_token: str (unique, nullable) # for REST API auth
    is_active: bool (default True)
    created_at: datetime
    last_login: datetime (nullable)

# Per-user API keys for OCR engines (encrypted)
class UserOCRConfig:
    id: int (PK)
    user_id: FK -> User
    google_credentials_path: str (nullable)  # path to JSON
    mistral_api_key: str (nullable, encrypted)
    tesseract_cmd_path: str (nullable)        # custom tesseract.exe path on Windows
    updated_at: datetime

# OCR Job (one PDF = one job)
class OCRJob:
    id: int (PK)
    user_id: FK -> User
    original_filename: str
    stored_filename: str          # UUID-based name in uploads/
    file_size_bytes: int
    page_count: int (nullable until processed)
    engine: str                   # 'google_vision' | 'mistral' | 'paddle' | 'tesseract'
    status: str                   # 'pending' | 'processing' | 'completed' | 'failed'
    source: str                   # 'web' | 'api' | 'folder_watch'
    error_message: text (nullable)
    progress_percent: int (default 0)
    created_at: datetime
    started_at: datetime (nullable)
    completed_at: datetime (nullable)

# OCR Result (one row per page)
class OCRResult:
    id: int (PK)
    job_id: FK -> OCRJob (cascade delete)
    page_number: int
    text_content: text            # extracted text
    raw_response: JSONB (nullable) # full engine response for debug/tables
    confidence_score: float (nullable)
    created_at: datetime

    # Index: GIN index on text_content using pg_trgm for fuzzy search
    # Index: GIN index on raw_response (JSONB)
```

### Required indexes
- `OCRResult.text_content` — GIN trigram index for `unaccent()` full-text search
- `OCRJob (user_id, created_at DESC)` — for user's job list
- `OCRJob (status)` — for finding pending jobs

---

## 5. Authentication & User Management

### Roles
- **admin**: full access including user management at `/admin/users`
- **user**: own jobs only, can manage own API keys

### Required pages/features
1. **Register** (`/auth/register`) — email + username + password (min 8 chars)
2. **Login** (`/auth/login`) — username or email + password
3. **Logout** (`/auth/logout`)
4. **Profile** (`/auth/profile`) — change password, view/regenerate API token
5. **Settings** (`/settings`) — configure OCR engine credentials per user
6. **Admin: Users list** (`/admin/users`) — admin-only, CRUD users, change roles

### Security
- Password hashing: `werkzeug.security.generate_password_hash` with `pbkdf2:sha256`
- CSRF protection on all forms (Flask-WTF default)
- API token: 64-char URL-safe random string, regeneratable
- API auth: `Authorization: Bearer <token>` header
- Session cookie: `SECURE=True` in production, `HTTPONLY=True`, `SAMESITE='Lax'`
- Encrypt Mistral API key in DB using `cryptography.fernet` (key in .env as `ENCRYPTION_KEY`)

### Initial admin user
On first run, create default admin if no users exist:
- Username: `admin`
- Password: `admin123` (force change on first login — show banner)
- Email: `admin@local`

---

## 6. OCR Engine Adapters

### Common interface (app/ocr/base.py)

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

@dataclass
class PageResult:
    page_number: int
    text: str
    confidence: Optional[float] = None
    raw_response: Optional[dict] = None

class OCREngine(ABC):
    name: str  # 'google_vision', etc.

    @abstractmethod
    def is_configured(self, user_config) -> bool:
        """Check if user has provided required credentials."""

    @abstractmethod
    def ocr_image(self, image_path: str, user_config) -> PageResult:
        """OCR a single page image. Page number set by caller."""

    def ocr_pdf(self, pdf_path: str, user_config, progress_callback=None) -> list[PageResult]:
        """Default: convert PDF→images, then OCR each page sequentially."""
        # Implementation in base class using pdf_utils.py
```

### Engine-specific notes

**Google Cloud Vision** (`google_vision.py`)
- Use `google.cloud.vision.ImageAnnotatorClient`
- Set credentials via `GOOGLE_APPLICATION_CREDENTIALS` env or per-user JSON path
- Use `document_text_detection` (best for dense text, Vietnamese supported)
- Response: `response.full_text_annotation.text`

**Mistral OCR** (`mistral.py`)
- Use `mistralai` Python SDK
- Endpoint: `client.ocr.process(model="mistral-ocr-latest", document={...})`
- Can send PDF directly (no need to split to images) — this is a big advantage
- Returns markdown-structured output preserving tables

**PaddleOCR** (`paddle.py`)
- `from paddleocr import PaddleOCR`
- Initialize with `lang='vi'` for Vietnamese
- For tables: use `PPStructure` with `table=True`
- Heavy first-time download (~500MB models) — log progress
- Recommend GPU but should work CPU-only

**Tesseract** (`tesseract.py`)
- `import pytesseract`
- Allow user to override `pytesseract.tesseract_cmd` path
- Use `pytesseract.image_to_string(img, lang='vie')`
- Document Windows install:
  - Download UB Mannheim build: https://github.com/UB-Mannheim/tesseract/wiki
  - Install Vietnamese tessdata
  - Default path: `C:\Program Files\Tesseract-OCR\tesseract.exe`

### Factory (app/ocr/factory.py)

```python
def get_engine(name: str) -> OCREngine:
    engines = {
        'google_vision': GoogleVisionOCR,
        'mistral': MistralOCR,
        'paddle': PaddleOCR,
        'tesseract': TesseractOCR,
    }
    if name not in engines:
        raise ValueError(f"Unknown engine: {name}")
    return engines[name]()
```

---

## 7. OCR Service & Job Processing

### app/services/ocr_service.py

- Single global `ThreadPoolExecutor(max_workers=2)` for OCR jobs (configurable)
- `submit_job(job_id)` — picks up pending job, marks `processing`, runs engine, saves results
- Update `OCRJob.progress_percent` after each page
- On failure: set `status='failed'`, save `error_message`, do NOT raise
- On success: set `status='completed'`, write results to DB in a single transaction

### app/services/folder_watcher.py

- Background thread started in `app/__init__.py` (only if `FOLDER_WATCH_ENABLED=true`)
- Polls `WATCH_FOLDER_PATH` every 30 seconds (configurable)
- For each `.pdf` file found:
  - Create OCRJob with `source='folder_watch'`, owner = configured `WATCH_FOLDER_USER_ID` (default admin)
  - Use engine specified by `WATCH_FOLDER_ENGINE` env var
  - Submit to OCR service
  - On completion, move file to `WATCH_FOLDER_PROCESSED_PATH`
- Log all activity to `logs/folder_watcher.log`

---

## 8. REST API

Base path: `/api/v1/`

All endpoints require `Authorization: Bearer <api_token>` header except where noted.

### Endpoints

| Method | Path | Description |
|---|---|---|
| POST | `/api/v1/ocr` | Upload PDF + start OCR job. Form-data: `file` (PDF), `engine` (string). Returns job ID. |
| GET | `/api/v1/jobs` | List current user's jobs. Query: `status`, `engine`, `limit`, `offset`. |
| GET | `/api/v1/jobs/<id>` | Get job status + metadata. |
| GET | `/api/v1/jobs/<id>/results` | Get OCR results. Query: `format=json|text|markdown`. |
| GET | `/api/v1/jobs/<id>/results/<page>` | Get single page result. |
| DELETE | `/api/v1/jobs/<id>` | Delete job + results + file. |
| GET | `/api/v1/engines` | List available engines + user's configuration status. |

### Response format (consistent envelope)

```json
{
  "success": true,
  "data": { ... },
  "error": null,
  "meta": { "page": 1, "total": 100 }
}
```

Errors:
```json
{
  "success": false,
  "data": null,
  "error": { "code": "INVALID_FILE", "message": "File must be PDF" }
}
```

### Rate limiting
Use `Flask-Limiter`: 60 requests/minute per token (configurable in .env).

---

## 9. UI Design — Galaxy UI Theme

### Aesthetic direction
- **Dark space theme**: deep navy (#0a0e27) and purple (#1a1147) gradients
- **Accent colors**: neon cyan (#00f0ff), magenta (#ff2e9a), starlight white
- **Typography**: Inter or Poppins for body, Orbitron or Space Grotesk for headings
- **Effects**: subtle starfield background (CSS animated dots), glassmorphism cards (`backdrop-filter: blur`), neon glow on focus/hover
- **Bootstrap 5.3.x** as foundation, custom CSS (`galaxy.css`) overrides for theme

### Reference implementation in `static/css/galaxy.css`

```css
:root {
  --galaxy-bg: #0a0e27;
  --galaxy-bg-2: #1a1147;
  --galaxy-card: rgba(255, 255, 255, 0.05);
  --galaxy-border: rgba(255, 255, 255, 0.1);
  --galaxy-cyan: #00f0ff;
  --galaxy-magenta: #ff2e9a;
  --galaxy-text: #e8e9f3;
  --galaxy-text-muted: #8b8fa8;
}

body {
  background: linear-gradient(135deg, var(--galaxy-bg) 0%, var(--galaxy-bg-2) 100%);
  color: var(--galaxy-text);
  font-family: 'Inter', sans-serif;
  min-height: 100vh;
  position: relative;
  overflow-x: hidden;
}

/* Animated starfield using ::before pseudo + radial gradients */
body::before {
  content: '';
  position: fixed;
  inset: 0;
  background-image:
    radial-gradient(2px 2px at 20% 30%, white, transparent),
    radial-gradient(1px 1px at 60% 70%, white, transparent),
    radial-gradient(1.5px 1.5px at 80% 20%, white, transparent);
  background-size: 200px 200px;
  animation: drift 60s linear infinite;
  opacity: 0.3;
  pointer-events: none;
}

.card {
  background: var(--galaxy-card);
  border: 1px solid var(--galaxy-border);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
}

.btn-primary {
  background: linear-gradient(135deg, var(--galaxy-cyan), var(--galaxy-magenta));
  border: none;
  font-weight: 600;
  transition: all 0.3s;
}

.btn-primary:hover {
  box-shadow: 0 0 20px rgba(0, 240, 255, 0.5);
  transform: translateY(-2px);
}

/* ... headings, inputs, navbar, badges all themed ... */
```

### Pages required

1. **Login / Register** — centered card, glassmorphism, subtle starfield
2. **Dashboard** (`/`) — stats: total jobs, pages OCR'd, by engine; recent jobs table
3. **Upload** (`/upload`) — drag-drop zone, engine selector (cards with logos), submit
4. **Jobs list** (`/jobs`) — filterable table: filename, engine, status (badge), pages, created, actions
5. **Job detail** (`/jobs/<id>`) — metadata + per-page accordion of extracted text + download buttons (TXT/JSON/MD)
6. **Settings** (`/settings`) — tabs for each OCR engine, API key inputs, test connection button
7. **Admin: Users** (`/admin/users`) — table with role badges, edit/delete

### Interactivity
- File upload uses **fetch + FormData** (no jQuery), shows progress bar during upload
- Job status polled every 3 seconds via `GET /api/v1/jobs/<id>` until completed/failed
- Toast notifications on success/error (Bootstrap Toast)
- Live page count update during processing

### Bootstrap CDN to use (in base.html)

```html
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Orbitron:wght@500;700&display=swap" rel="stylesheet">
<link href="{{ url_for('static', filename='css/galaxy.css') }}" rel="stylesheet">
<!-- ... -->
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
```

---

## 10. Configuration (.env)

Generate `.env.example` with these keys:

```ini
# Flask
FLASK_APP=run.py
FLASK_ENV=development
SECRET_KEY=change-me-to-random-64-chars
ENCRYPTION_KEY=generate-with-Fernet.generate_key

# Database
DATABASE_URL=postgresql+psycopg://postgres:Phuong2606@localhost:5432/vic_ocr

# File storage
UPLOAD_FOLDER=./uploads
OUTPUT_FOLDER=./outputs
MAX_UPLOAD_MB=50

# OCR
OCR_MAX_WORKERS=2
PDF_DPI=200                        # for pdf2image conversion
POPPLER_PATH=                      # Windows: C:\poppler-xx\Library\bin

# Folder watcher
FOLDER_WATCH_ENABLED=false
WATCH_FOLDER_PATH=./watch_folder
WATCH_FOLDER_PROCESSED_PATH=./watch_folder_processed
WATCH_FOLDER_USER_ID=1
WATCH_FOLDER_ENGINE=tesseract
WATCH_INTERVAL_SECONDS=30

# Google Vision (system-wide fallback if user has no own config)
GOOGLE_APPLICATION_CREDENTIALS=./credentials/google-vision.json

# Mistral (system-wide fallback)
MISTRAL_API_KEY=

# Tesseract Windows path
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe

# Rate limiting
API_RATE_LIMIT=60/minute
```

---

## 11. requirements.txt

```
Flask>=3.0
Flask-SQLAlchemy>=3.1
Flask-Migrate>=4.0
Flask-Login>=0.6
Flask-WTF>=1.2
Flask-Limiter>=3.5
psycopg[binary]>=3.1
SQLAlchemy>=2.0
python-dotenv>=1.0
cryptography>=42.0
Werkzeug>=3.0

# PDF processing
pdf2image>=1.17
Pillow>=10.0
pypdf>=4.0

# OCR engines
google-cloud-vision>=3.7
mistralai>=1.0
pytesseract>=0.3.10
paddleocr>=2.7
paddlepaddle>=2.6

# Utilities
requests>=2.31
python-magic-bin>=0.4.14 ; sys_platform == 'win32'
python-magic>=0.4.27 ; sys_platform != 'win32'
```

---

## 12. Setup Instructions (include in README.md)

### Prerequisites (Windows)
1. **Python 3.11+** — already installed
2. **PostgreSQL 16+** — already installed (port 5432, password: Phuong2606)
3. **Poppler for Windows** — download from https://github.com/oschwartz10612/poppler-windows/releases, extract, add to PATH or set `POPPLER_PATH` in .env
4. **Tesseract OCR** (optional, only if using Tesseract engine) — UB Mannheim build, install Vietnamese language data
5. **Google Cloud service account JSON** (optional, for Google Vision) — place in `credentials/`
6. **Mistral API key** (optional, for Mistral OCR) — get from console.mistral.ai

### Install steps

```powershell
# 1. Clone / extract project
cd vic_ocr

# 2. Create virtual environment
python -m venv venv
.\venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Copy and edit .env
copy .env.example .env
# (edit DATABASE_URL, SECRET_KEY, ENCRYPTION_KEY, etc.)

# 5. Generate keys
python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"
python -c "from cryptography.fernet import Fernet; print('ENCRYPTION_KEY=' + Fernet.generate_key().decode())"

# 6. Create database (run in psql or pgAdmin)
# CREATE DATABASE vic_ocr;

# 7. Initialize migrations
flask db init
flask db migrate -m "initial schema"
flask db upgrade

# 8. Run app
python run.py
# Open http://localhost:5000
# Login: admin / admin123 (change on first login)
```

---

## 13. Code Quality Requirements

- **Type hints** on all function signatures
- **Docstrings** on all public classes/functions (Google style)
- **Error handling**: never swallow exceptions silently — log + return user-friendly message
- **Logging**: use `app.logger`, write to `logs/app.log` with rotation (RotatingFileHandler, 10MB × 5 files)
- **No hardcoded secrets** — everything via .env
- **Vietnamese-friendly**: ensure UTF-8 throughout (file reads, DB connection, HTTP responses)
- **Forms**: all use Flask-WTF with CSRF
- **SQL injection**: use SQLAlchemy ORM only, no raw SQL with string concatenation
- **File uploads**: validate MIME type (use `python-magic`), enforce max size, sanitize filenames with `werkzeug.utils.secure_filename`

---

## 14. Acceptance Checklist

Before considering done, verify:

- [ ] App starts with `python run.py` on Windows without errors
- [ ] Default admin user created on first run
- [ ] User can register, login, logout
- [ ] Admin can list/create/edit/delete users at `/admin/users`
- [ ] User can upload PDF via web UI, select engine, see job in jobs list
- [ ] All 4 OCR engines selectable (graceful error if not configured for that user)
- [ ] At least Tesseract works end-to-end on the Vingroup test PDF
- [ ] Job status updates live (polling)
- [ ] Results viewable per-page in UI
- [ ] User can download results as TXT and JSON
- [ ] REST API: token auth works, can POST a PDF and retrieve results
- [ ] Folder watcher: enabling it picks up PDFs and processes them
- [ ] Galaxy UI theme applied — dark, starfield, glassmorphism cards
- [ ] Mobile-responsive (Bootstrap defaults)
- [ ] No secrets in committed code

---

## 15. Build Order (suggested)

To make incremental progress visible, build in this order:

1. **Skeleton**: Flask app factory, config, extensions, base template, `/` route showing "Hello"
2. **Galaxy UI theme**: base.html with Bootstrap + galaxy.css, navbar, footer
3. **Database + migrations**: User model, run migrate, create admin user on startup
4. **Auth**: register/login/logout/profile pages
5. **Admin user management**: CRUD users
6. **OCR base**: abstract class, factory, PDF utils, Tesseract adapter only
7. **Upload UI + Job model**: upload page, save file, create job, run synchronously first
8. **Async with ThreadPoolExecutor**: convert to background processing, status polling
9. **Other engines**: Google Vision, Mistral, PaddleOCR adapters
10. **Settings page**: per-user OCR config (encrypted Mistral key, paths, JSON upload)
11. **REST API**: token auth, all endpoints
12. **Folder watcher**: background thread, integration test
13. **Polish**: error pages, toasts, mobile tweaks, README

After each step: commit, run, smoke-test before moving on.

---

## 16. Important Reminders for Claude Code

- **Read this entire file first** before writing any code
- **Don't skip features** — all 4 OCR engines, all 3 input methods, full user mgmt are required
- **Galaxy UI is required** — don't ship default Bootstrap; the custom dark theme is part of the spec
- **Test the Tesseract path early** — it's the simplest engine and will surface install issues fastest
- **Use Bootstrap 5.3.x latest** — check https://getbootstrap.com for current version when starting
- **All UI labels in Vietnamese** (e.g., "Đăng nhập", "Tải lên", "Công việc", "Cài đặt"), code identifiers in English
- **Windows path handling**: use `pathlib.Path` everywhere, not string concat with `\`
- **Test with the actual PDF**: `VIC_Baocaotaichinh_2025_Kiemtoan_Hopnhat.pdf` (~14 MB, 126 pages, scanned, Vietnamese)

End of spec. Build it well.
