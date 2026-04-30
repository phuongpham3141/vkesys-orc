# VIC OCR (vkesys-orc) — Project Handoff Document

> **Mục đích file này**: Cung cấp đầy đủ context cho session Claude Code tiếp theo
> để (1) hiểu project đang ở đâu, (2) tiếp tục công việc còn dang dở,
> (3) tích hợp với hệ thống chấm điểm ESG sắp tới.
>
> **Đọc theo thứ tự**: TL;DR → Trạng thái hiện tại → Kiến trúc → ESG Roadmap.

---

## 0. TL;DR — Đọc trong 60 giây

| | |
|---|---|
| **Repo** | `c:\vkesys-orc` (local), GitHub `phuongpham3141/vkesys-orc` **chưa tạo** |
| **Branch** | `main`, **21 commit chưa push** |
| **Stack** | Flask 3 + PostgreSQL 16 + 6 OCR engines + Galaxy UI dark theme |
| **Kiến trúc** | 2 process: Flask web + scheduler. Mỗi job = subprocess riêng (cửa sổ Python console) |
| **Use case chính** | OCR PDF báo cáo tài chính tiếng Việt (Vingroup, ~90-216 trang/file) → trích bảng → xuất CSV/XLSX |
| **Engine recommended** | **Document AI Layout** (đã verify work với Vingroup PDF). Gemini hết credits của user, Mistral chưa test |
| **Tài khoản test** | `admin` / `Phuong2606$$` — admin với full permission |
| **Database** | `postgresql+psycopg://postgres:Phuong2606@localhost:5432/vic_ocr` |
| **Khởi động** | Double-click `start.bat` (mở Flask + scheduler trong 2 cửa sổ) |
| **Sản phẩm tiếp theo** | Hệ thống chấm điểm ESG sẽ dùng OCR results làm input — xem section "ESG Integration" |

---

## 1. Trạng thái hiện tại (snapshot last commit)

### ✅ Đã hoàn thành & verified

- ✅ Flask app factory, models, blueprints (auth/admin/main/api), Galaxy UI dark theme
- ✅ User management, API token Bearer auth, Fernet encryption cho cloud keys
- ✅ Folder watcher (auto-OCR PDF drop vào watch folder)
- ✅ 6 OCR engines registered: `google_vision`, `document_ai`, `gemini`, `mistral`, `paddle`, `tesseract`
- ✅ Tesseract 5.5.0 + Vietnamese tessdata cài tự động (`scripts/install_tesseract.ps1`)
- ✅ Poppler 25.12.0 cài tự động (`scripts/install_poppler.ps1`) cho `pdf2image`
- ✅ Document AI Layout Parser parse đúng `document_layout.blocks` tree (verify với job 7 page 66 — trả 1407 chars + 1 bảng VinFast/Vingroup Investment/VinAI)
- ✅ Page-by-page atomic processing: `DOCUMENT_AI_PAGES_PER_REQUEST=1` mặc định
- ✅ Incremental save: mỗi page xong → INSERT DB ngay (transaction riêng) → fail giữa chừng vẫn giữ pages đã xong
- ✅ Resume on retry: skip pages đã saved → không tốn tiền API
- ✅ "Test single page" button: `target_pages=[N]` → engine chỉ chạy đúng 1 page
- ✅ Subset PDF cho Gemini/Mistral: khi `target_pages` set, build PDF nhỏ chứa chỉ pages đó (tiết kiệm token ~90×)
- ✅ Stop / Stop All buttons: `taskkill /F /T /PID <runner_pid>` thông qua DB-tracked PID
- ✅ Per-job subprocess console: scheduler `subprocess.Popen(creationflags=CREATE_NEW_CONSOLE)` cho mỗi job
- ✅ DB-backed settings (`Setting` table) editable tại `/admin/settings`: `MAX_CONCURRENT_WORKERS` (1-20), `DOCUMENT_AI_PAGES_PER_REQUEST` (1-30), `WORKER_SPAWN_CONSOLE` (bool)
- ✅ Scheduler heartbeat → `LAST_SCHEDULER_HEARTBEAT` setting → admin UI hiển thị age realtime
- ✅ Test Spawn button trong settings để verify cơ chế CREATE_NEW_CONSOLE
- ✅ Export TXT / JSON / Markdown / **CSV (UTF-8 BOM)** / **XLSX (1 sheet/bảng)** với fallback parse Markdown table cho Gemini/Mistral
- ✅ "Run again" với optional engine swap (cùng engine = resume, khác engine = wipe + start fresh)
- ✅ Empty/fallback OCRResult auto-cleanup khi retry / test-page (tránh "Trang không có văn bản" rác)
- ✅ Honest status: nếu engine trả 0 pages mà expected > 0 → mark `failed` với hướng dẫn xem log

### 🚧 Outstanding / partially working

- ⚠️ **Gemini engine chưa verify**: user `gemini-2.5-pro` API key bị `429 ResourceExhausted: prepayment credits depleted`. Code đã đúng nhưng chưa thực test với key có credit.
- ⚠️ **Mistral engine chưa verify**: chưa nhập API key → chưa test
- ⚠️ **PaddleOCR chưa verify**: package có sẵn (cài qua pip) nhưng user chưa thử
- ⚠️ **GitHub repo chưa tạo**: 21 commit local đang đợi `gh repo create phuongpham3141/vkesys-orc --public --push` hoặc tạo manual qua web
- ⚠️ **Werkzeug auto-reloader OFF default**: `FLASK_AUTO_RELOAD=true` trong `.env` để bật lại nếu cần dev hot-reload (đã off vì gây crash với long-running OCR threads)
- ⚠️ **Folder watcher mặc định OFF**: `FOLDER_WATCH_ENABLED=false` trong `.env`

### ❌ Không có / cố ý không làm

- ❌ Celery/Redis: scope nhỏ, dùng ThreadPoolExecutor + subprocess (đủ dùng cho 1 server, đến ~20 concurrent jobs)
- ❌ Job cancel during processing (mềm): chỉ kill PID (cứng). OK vì OCR API đã tốn tiền dù sao
- ❌ Multi-tenant isolation: 1 instance = 1 organization (mỗi user thấy job riêng, admin thấy tất cả)
- ❌ Real-time updates qua WebSocket: dùng polling 3s ở `/api/v1/jobs/<id>/public`

---

## 2. Kiến trúc tổng quan

### 2 process model

```
┌─────────────────────────────────────────────┐
│  Cửa sổ 1 (foreground): python run.py       │
│  Flask web :8000                            │
│  - Render UI Galaxy theme                   │
│  - REST API /api/v1/*                       │
│  - INSERT pending OCRJob row khi user upload│
│  - KHÔNG xử lý OCR (OCR_WORKER_MODE=external)│
└─────────────────────────────────────────────┘
                    ↕ DB
┌─────────────────────────────────────────────┐
│  Cửa sổ 2 (popup): python worker.py         │
│  Scheduler — poll DB mỗi 2s                 │
│  - Read MAX_CONCURRENT_WORKERS from DB      │
│  - SELECT FOR UPDATE SKIP LOCKED → claim 1  │
│  - Update LAST_SCHEDULER_HEARTBEAT          │
│  - subprocess.Popen(CREATE_NEW_CONSOLE) ─┐  │
└────────────────────────────────────────── │ ─┘
                                            ↓
       ┌─ Cửa sổ 3,4,5...: 1 cho mỗi job ──┐
       │ python run_one_job.py <job_id>    │
       │ - VIC_NO_BOOTSTRAP=1 (skip schema)│
       │ - OCRService.run_job_safe(id)     │
       │ - Inprocess mode, runs synchronously│
       │ - Each page → INSERT OCRResult ngay│
       │ - Final status update DB           │
       │ - Pause input() để xem log        │
       └────────────────────────────────────┘
```

### Luồng dữ liệu OCR

```
1. User upload PDF qua web/API/folder watcher
2. save PDF → uploads/<uuid>.pdf (tuyệt đối path từ BASE_DIR)
3. INSERT OCRJob (status='pending', engine, source, ...)
4. ocr_service.submit_job(id) → no-op (external mode)
5. Scheduler polls (≤2s) → claim job → spawn run_one_job.py <id>
6. Subprocess:
   a. pypdf đọc total pages → SET page_count
   b. existing_pages = SELECT page_number FROM ocr_results WHERE job_id=N
   c. target_pages = job.target_pages (nullable, từ "Test 1 trang")
   d. engine.ocr_pdf(pdf_path, on_page_result=save_page,
                     skip_pages=existing, target_pages=target)
   e. Mỗi page xong → callback save_page → INSERT OCRResult (own transaction)
   f. Cuối: count saved, nếu 0 mà expected>0 → mark failed, else completed
7. UI poll /api/v1/jobs/<id>/public mỗi 3s → update progress bar
8. User click Tải xuống → export CSV/XLSX/TXT/JSON/MD vào outputs/
```

### Decision tree mỗi engine

```
engine.ocr_pdf(pdf, ...) phân hoá:
│
├── Tesseract / Google Vision / Paddle (no native PDF):
│   └── default base impl: pdf2image → PNG tạm → ocr_image() từng PNG
│
├── Document AI (native PDF, chunked):
│   └── pypdf split per chunk_size pages → process_document → walk
│       document_layout.blocks tree → group theo page_span
│
├── Mistral (native PDF, all-at-once):
│   └── if target_pages: build subset PDF first (tiết kiệm)
│       send → ocr.process → response.pages[].markdown → split per-page
│
└── Gemini (native PDF, all-at-once):
    └── if target_pages: build subset PDF first
        send + prompt "Trang N separator" → response.text → regex split
        remap page_number subset→original
```

---

## 3. File structure & vai trò

```
c:\vkesys-orc\
├── app/
│   ├── __init__.py             # create_app(); _ensure_schema (ALTER IF NOT EXISTS);
│   │                           # _bootstrap_admin (skip nếu VIC_NO_BOOTSTRAP=1);
│   │                           # _start_folder_watcher
│   ├── config.py               # BaseConfig với _abs() resolve relative paths;
│   │                           # OCR_WORKER_MODE (external/inprocess)
│   ├── extensions.py           # db, login_manager, csrf, limiter
│   ├── models.py               # User, UserOCRConfig (Fernet-encrypted keys),
│   │                           # OCRJob (target_pages JSONB, runner_pid),
│   │                           # OCRResult (raw_response JSONB chứa tables),
│   │                           # Setting (key/value runtime config)
│   │
│   ├── auth/                   # /auth/login, register, logout, profile
│   ├── admin/                  # /admin/users (CRUD), /admin/settings (DB tunables),
│   │                           # /admin/settings/test-spawn (verify CREATE_NEW_CONSOLE)
│   ├── main/                   # /, /upload, /jobs, /jobs/<id>, /jobs/<id>/{retry,stop,
│   │                           # test-page,download/<fmt>}, /jobs/stop-all,
│   │                           # /settings (per-user OCR config),
│   │                           # /settings/gemini/models (Load models button)
│   ├── api/                    # /api/v1/{ocr,jobs,jobs/<id>,jobs/<id>/results,
│   │                           # jobs/<id>/results/<page>,jobs/<id>/retry,
│   │                           # engines,worker/status}, Bearer token auth
│   │
│   ├── ocr/
│   │   ├── base.py             # OCREngine ABC + default ocr_pdf (PDF→image loop);
│   │   │                       # PageResult dataclass; signature thêm
│   │   │                       # on_page_result + skip_pages + target_pages
│   │   ├── factory.py          # get_engine(name) + ENGINE_LABELS metadata
│   │   ├── pdf_utils.py        # pdf_to_images (Poppler), get_page_count (pypdf)
│   │   ├── document_ai.py      # DEFAULT_PAGES_PER_REQUEST=1; explicit
│   │   │                       # service_account.Credentials; chunk loop;
│   │   │                       # _extract_from_layout walks blocks tree;
│   │   │                       # _extract_from_legacy_pages fallback
│   │   ├── gemini.py           # google.generativeai SDK; Markdown prompt với
│   │   │                       # ===== Trang N ===== separator; subset PDF
│   │   ├── mistral.py          # mistralai SDK; native PDF; subset PDF
│   │   ├── google_vision.py    # ImageAnnotatorClient.document_text_detection
│   │   ├── paddle.py           # paddleocr.PaddleOCR(lang='vi'), shared instance
│   │   └── tesseract.py        # pytesseract.image_to_string(lang='vie')
│   │
│   ├── services/
│   │   ├── ocr_service.py      # OCRService với 2 mode:
│   │   │                       # - external: submit_job no-op
│   │   │                       # - inprocess: ThreadPoolExecutor (legacy, dev only)
│   │   │                       # _run_job: query existing, pass skip+target,
│   │   │                       # save_page callback (own transaction), final status
│   │   ├── folder_watcher.py   # Background thread, scan WATCH_FOLDER_PATH mỗi 30s
│   │   ├── settings.py         # get_setting / set_setting helpers,
│   │   │                       # SETTING_DEFAULTS dict, list_settings cho admin UI
│   │   └── storage.py          # save_uploaded_pdf, export_results_*
│   │                           # (txt/json/md/csv/xlsx); _collect_tables ưu tiên
│   │                           # raw_response['tables'] rồi parse Markdown
│   │
│   ├── static/
│   │   ├── css/galaxy.css      # Theme: cyan/magenta gradient, glassmorphism,
│   │   │                       # animated starfield, neon hover
│   │   ├── js/app.js           # VIC.showToast, VIC.csrfToken, VIC.formatBytes
│   │   └── js/upload.js        # Drag-drop + XHR upload với progress bar
│   │
│   └── templates/
│       ├── base.html           # Galaxy nav, dropdown admin (Users/Settings),
│       │                       # CSRF meta, toast container
│       ├── auth/               # login.html, register.html, profile.html
│       ├── admin/              # users.html, user_form.html, settings.html
│       ├── main/               # dashboard.html (stats), upload.html (engine cards),
│       │                       # jobs.html (list + Stop all), job_detail.html
│       │                       # (Stop, Retry, Test 1 trang, Tải xuống dropdown),
│       │                       # settings.html (per-user OCR config tabs)
│       └── errors/             # 404.html, 500.html
│
├── docs/
│   ├── GOOGLE_VISION_SETUP.md           # 6 bước tạo Service Account JSON
│   ├── DOCUMENT_AI_AND_GEMINI_SETUP.md  # Tạo Layout Parser processor + Gemini key
│   └── HANDOFF.md                       # ← BẠN ĐANG ĐỌC
│
├── scripts/
│   ├── init_db.py              # Tạo DB vic_ocr + extensions unaccent, pg_trgm
│   ├── reset_admin.py          # Reset admin password: <user> <password>
│   ├── verify_gcp.py           # Chẩn đoán Document AI config (CONSUMER_INVALID, etc)
│   ├── install_tesseract.ps1   # UB Mannheim 5.5.0 + vie.traineddata
│   └── install_poppler.ps1     # Latest oschwartz10612/poppler-windows
│
├── uploads/                    # PDF user upload (gitignored, đường dẫn tuyệt đối)
├── outputs/                    # Export files (gitignored)
├── watch_folder/               # Folder watcher input (gitignored)
├── watch_folder_processed/     # Đã xử lý (gitignored)
├── credentials/                # Google SA JSON (gitignored, chứa google-vision.json)
├── logs/
│   ├── app.log                 # Flask logger (RotatingFileHandler 10MB×5)
│   ├── scheduler.log           # worker.py output
│   ├── folder_watcher.log      # folder_watcher.py
│   └── jobs/job_<id>.log       # 1 file/job từ run_one_job.py
│
├── migrations/                 # Alembic (init'd nhưng schema chính qua _ensure_schema)
├── .env / .env.example         # ENCRYPTION_KEY (Fernet), SECRET_KEY, DATABASE_URL,
│                               # OCR_WORKER_MODE, FLASK_AUTO_RELOAD, ...
├── start.bat                   # One-click: venv → pip → DB init → migrate →
│                               # spawn worker.bat → run.py
├── stop.bat                    # taskkill port 8000 + window "VIC OCR Worker"
├── worker.bat                  # python worker.py (scheduler)
├── worker.py                   # Scheduler chính (claim + spawn subprocess)
├── run_one_job.py              # Single-job runner (subprocess được spawn)
├── run.py                      # Flask dev entry, port 8000, reloader off default
├── wsgi.py                     # Production entry (waitress/gunicorn)
└── requirements.txt
```

---

## 4. Database schema (đã apply)

### `users`
| col | type | notes |
|---|---|---|
| id | int PK | |
| username | varchar(64) UNIQUE INDEX | |
| email | varchar(255) UNIQUE INDEX | |
| password_hash | varchar(255) | pbkdf2:sha256 |
| role | varchar(16) | 'admin' / 'user' |
| api_token | varchar(128) UNIQUE | secrets.token_urlsafe(48) |
| is_active | bool | |
| must_change_password | bool | force change banner |
| created_at, last_login | datetime | |

### `user_ocr_configs`
| col | type | notes |
|---|---|---|
| id | int PK | |
| user_id | FK users CASCADE UNIQUE | |
| google_credentials_path | varchar(512) | path JSON SA |
| mistral_api_key_encrypted | text | Fernet |
| tesseract_cmd_path | varchar(512) | optional override |
| **documentai_project_id** | varchar(128) | added later |
| **documentai_location** | varchar(32) | 'us'/'eu'/'asia-northeast1' |
| **documentai_processor_id** | varchar(128) | 16-char hex |
| **gemini_api_key_encrypted** | text | Fernet |
| **gemini_model** | varchar(64) | 'gemini-2.5-pro' default |
| updated_at | datetime | onupdate |

### `ocr_jobs`
| col | type | notes |
|---|---|---|
| id | int PK | |
| user_id | FK users CASCADE | |
| original_filename | varchar(512) | display name |
| stored_filename | varchar(512) | UUID-based |
| file_size_bytes | bigint | |
| page_count | int nullable | |
| engine | varchar(32) | one of 6 names |
| status | varchar(16) INDEX | 'pending'/'processing'/'completed'/'failed' |
| source | varchar(16) | 'web'/'api'/'folder_watch' |
| error_message | text | populated on failure |
| progress_percent | int | 0-100 |
| **target_pages** | JSONB | list[int], for Test 1 trang |
| **runner_pid** | int | OS PID of subprocess (for Stop) |
| created_at, started_at, completed_at | datetime | |

Index: `(user_id, created_at DESC)` cho user job list.

### `ocr_results`
| col | type | notes |
|---|---|---|
| id | int PK | |
| job_id | FK ocr_jobs CASCADE | |
| page_number | int | 1-indexed |
| text_content | text | OCR text, có thể chứa Markdown table inline |
| **raw_response** | JSONB | engine-specific: `tables` cell matrix, `confidence`, etc |
| confidence_score | float nullable | |
| created_at | datetime | |

Indexes:
- GIN trigram trên `text_content` cho fuzzy search Vietnamese
- GIN trên `raw_response` cho table query
- UNIQUE `(job_id, page_number)` — tránh duplicate

### `settings` (mới, runtime config)
| col | type | notes |
|---|---|---|
| key | varchar(64) PK | uppercase by convention |
| value | text | |
| description | varchar(255) | hiển thị admin UI |
| updated_at | datetime | onupdate |

Hiện đang dùng:
- `MAX_CONCURRENT_WORKERS` (1-20, default 2)
- `DOCUMENT_AI_PAGES_PER_REQUEST` (1-30, default 1)
- `WORKER_SPAWN_CONSOLE` (bool, default true)
- `LAST_SCHEDULER_HEARTBEAT` (ISO datetime, scheduler tự update mỗi poll)
- `LAST_SCHEDULER_PID` (int)

### Cách extend schema

`app/__init__.py:_ensure_schema()` chứa list `additive` của `(table, column, ddl)`. Thêm column mới = thêm tuple. Idempotent qua `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`. Mỗi ALTER trong transaction riêng (1 fail không hủy cả batch).

---

## 5. 6 OCR Engines — chi tiết

### Document AI Layout Parser ⭐ (recommended)

- **File**: `app/ocr/document_ai.py`
- **Status**: ✅ Verified với Vingroup PDF (job 7 page 66 → 1407 chars + 1 bảng)
- **Cấu hình**: Service Account JSON (chung với Vision) + GCP project_id + location + Layout Parser processor_id
- **Đặc điểm**:
  - Hiểu cấu trúc tài liệu phức tạp (sections, headings, tables, lists)
  - Trả `document.document_layout.blocks[]` với `page_span`, `text_block`, `table_block`, `list_block`
  - Adapter walk tree, group theo `block.page_span.page_start..page_end`
  - Bảng được lưu cell matrix vào `OCRResult.raw_response.tables` → CSV/XLSX export OK
  - Default 1 page/request (atomic, lưu DB sau từng page)
- **Cost**: ~$10/1k trang
- **Common error**:
  - `403 CONSUMER_INVALID` → sai Project ID (dùng `vkesys` chứ không phải `vic-ocr-layout`)
  - `400 PAGE_LIMIT_EXCEEDED` → đã fix bằng chunking 1 trang/request

### Gemini Multimodal

- **File**: `app/ocr/gemini.py`
- **Status**: ⚠️ Chưa verify (user hết credits Gemini Pro)
- **SDK**: `google-generativeai` (legacy), prompt chứa `===== Trang N =====` separator
- **Cấu hình**: API key từ <https://aistudio.google.com/apikey>, model name (default `gemini-2.5-pro`)
- **Có nút "Load models"** trong settings: gọi `genai.list_models()`, lọc model có `generateContent`, hiển thị thành chips để click chọn
- **Subset PDF**: nếu `target_pages` set → `_build_subset_pdf` (pypdf) → gửi PDF nhỏ → remap page numbers
- **Cost**: Pro ~$1.25/1M input tokens, Flash $0.075/1M
- **Common error**: `429 ResourceExhausted: prepayment credits depleted` → user nạp credits

### Mistral OCR

- **File**: `app/ocr/mistral.py`
- **Status**: ⚠️ Chưa test (user chưa nhập API key)
- **SDK**: `mistralai >= 1.0`, model `mistral-ocr-latest`
- **Native PDF**: gửi base64 entire document → response.pages[].markdown
- **Subset PDF**: tương tự Gemini cho test mode
- **Output**: Markdown table preserved
- **Cost**: ~$1/1k trang

### Google Cloud Vision

- **File**: `app/ocr/google_vision.py`
- **Method**: `document_text_detection` (best for dense text)
- **Cần**: Service Account JSON (cùng project có Document AI thì OK)
- **Limit**: Free 1,000 trang/tháng, sau đó $1.50/1k
- **Không hỗ trợ bảng cấu trúc** — chỉ text thuần

### PaddleOCR

- **File**: `app/ocr/paddle.py`
- **Local**: cài qua `pip install paddleocr paddlepaddle` (~2GB models lần đầu)
- **Cấu hình**: `PaddleOCR(lang='vi', use_angle_cls=True)` — instance shared global
- **Confidence per line**: lưu vào `raw_response.avg_confidence`
- **GPU**: tự detect, fallback CPU

### Tesseract

- **File**: `app/ocr/tesseract.py`
- **Status**: ✅ Cài đặt tự động qua `scripts/install_tesseract.ps1`
- **Path**: `C:\Program Files\Tesseract-OCR\tesseract.exe` + `vie.traineddata` từ tessdata_best
- **Limit**: Free, slow, không hiểu bảng phức tạp
- **Dùng tốt cho**: text thuần, scan chất lượng cao

---

## 6. Critical implementation details (đừng phá)

### 6.1 Đường dẫn tuyệt đối cho data folders
**Bug đã fix**: Flask 3 `send_file` resolve relative path theo `app.root_path` (= `app/`), nhưng `Path.mkdir/open` resolve theo CWD (= project root). File ghi đúng nhưng `send_file` đọc sai chỗ → 404.

**Fix**: `app/config.py:_abs()` chuyển mọi path data folder thành tuyệt đối anchored at `BASE_DIR` ngay khi load config. Áp dụng cho `UPLOAD_FOLDER`, `OUTPUT_FOLDER`, `WATCH_FOLDER_PATH`, `WATCH_FOLDER_PROCESSED_PATH`, `GOOGLE_APPLICATION_CREDENTIALS`.

### 6.2 Page-by-page atomic save với resume
- `OCREngine.ocr_pdf()` signature có `on_page_result: Callable[[PageResult], None]`
- Adapter gọi callback sau mỗi page xong
- Service supplies callback INSERT trong transaction riêng (không bị batch rollback)
- `skip_pages` set để retry không tốn tiền lại
- `target_pages` để test 1 trang

### 6.3 Document AI explicit credentials (không xài env var)
**Bug đã fix**: Dùng `os.environ["GOOGLE_APPLICATION_CREDENTIALS"]` global → giữa chunks bị stale → 401 CREDENTIALS_MISSING.

**Fix**: `service_account.Credentials.from_service_account_file()` explicit, build client 1 lần đầu `ocr_pdf`, reuse cho mọi chunk.

### 6.4 Subprocess per job với CREATE_NEW_CONSOLE
- Scheduler không tự xử lý OCR
- Mỗi job → `subprocess.Popen([sys.executable, "run_one_job.py", str(id)], creationflags=CREATE_NEW_CONSOLE)`
- Subprocess set `VIC_NO_BOOTSTRAP=1` → skip schema migration / admin bootstrap (parent đã làm)
- PID lưu vào `OCRJob.runner_pid` → web Stop button gọi `taskkill /F /T /PID <pid>`

### 6.5 Atomic claim với SKIP LOCKED
```sql
UPDATE ocr_jobs SET status='processing'
 WHERE id = (SELECT id FROM ocr_jobs WHERE status='pending'
             ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1)
 RETURNING id
```
An toàn khi chạy nhiều scheduler cùng lúc — never claim same job twice.

### 6.6 DB-backed settings với fallback chain
`get_setting(key)` đọc theo thứ tự: DB → `os.environ` → `SETTING_DEFAULTS` → caller default.

Admin UI hiển thị **source badge** (`db`/`env`/`default`) cho mỗi setting để minh bạch.

### 6.7 Galaxy UI là core, không default Bootstrap
- Specfile yêu cầu rõ
- `app/static/css/galaxy.css` ~370 dòng
- Variables `--galaxy-cyan`, `--galaxy-magenta`, glassmorphism, animated starfield qua `body::before`
- KHÔNG ship default Bootstrap cho production

### 6.8 Vietnamese UTF-8 throughout
- Form labels Vietnamese: "Đăng nhập", "Tải lên", "Công việc"
- Code identifiers English
- DB encoding UTF-8 (PostgreSQL default)
- File reads với `encoding='utf-8'`
- CSV export với UTF-8 BOM (Excel compatibility)

### 6.9 Werkzeug auto-reloader OFF default
**Lý do**: reloader detect file change giữa lúc OCR thread chạy → tear down sockets → `OSError WinError 10038`.

**Fix**: `run.py` set `use_reloader=False` mặc định. `FLASK_AUTO_RELOAD=true` để bật lại.

---

## 7. Configuration knobs

### `.env` file (file `.env.example` là template)

```ini
SECRET_KEY=64-char-hex                    # python -c "import secrets;print(secrets.token_hex(32))"
ENCRYPTION_KEY=fernet-base64               # Fernet.generate_key()
DATABASE_URL=postgresql+psycopg://postgres:Phuong2606@localhost:5432/vic_ocr
FLASK_HOST=0.0.0.0
FLASK_PORT=8000
FLASK_AUTO_RELOAD=false                    # bật khi dev hot-reload (cảnh báo crash)

UPLOAD_FOLDER=./uploads
OUTPUT_FOLDER=./outputs
MAX_UPLOAD_MB=50

OCR_MAX_WORKERS=2                          # legacy ThreadPoolExecutor
OCR_WORKER_MODE=external                   # external = subprocess, inprocess = legacy
DOCUMENT_AI_PAGES_PER_REQUEST=1            # 1 = atomic, 30 = max
PDF_DPI=200                                # cho pdf2image
POPPLER_PATH=C:\Program Files\poppler\Library\bin

FOLDER_WATCH_ENABLED=false
WATCH_FOLDER_PATH=./watch_folder
WATCH_INTERVAL_SECONDS=30

GOOGLE_APPLICATION_CREDENTIALS=./credentials/google-vision.json
MISTRAL_API_KEY=                           # fallback nếu user không config riêng
GEMINI_API_KEY=
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe

API_RATE_LIMIT=60/minute
```

### `/admin/settings` (DB-backed, override `.env`)

3 knobs editable không cần restart, áp dụng trong ≤2s (worker re-read).

---

## 8. Common operations

### Khởi động lần đầu
```cmd
:: Tự động hoàn toàn
start.bat
:: Sẽ:
:: 1. Tạo venv\
:: 2. pip install -r requirements.txt
:: 3. Sinh .env với SECRET_KEY + ENCRYPTION_KEY random
:: 4. Tạo DB vic_ocr + extensions
:: 5. flask db upgrade
:: 6. Spawn worker.bat trong cửa sổ riêng
:: 7. python run.py
```

### Khởi động hàng ngày (đã setup)
```cmd
start.bat              :: Spawn 2 cửa sổ
:: web: http://localhost:8000
:: login: admin / Phuong2606$$
```

### Reset admin password
```cmd
venv\Scripts\python.exe scripts\reset_admin.py admin <new_password>
```

### Verify GCP config khi Document AI fail
```cmd
venv\Scripts\python.exe scripts\verify_gcp.py
:: In ra: Project ID có khớp JSON không? Processor tồn tại không?
:: Hint cho từng error code
```

### Stop tất cả
```cmd
stop.bat              :: Kill port 8000 + window "VIC OCR Worker"
```

### Cài Tesseract / Poppler từ đầu
```cmd
powershell -ExecutionPolicy Bypass -File scripts\install_tesseract.ps1
powershell -ExecutionPolicy Bypass -File scripts\install_poppler.ps1
```

### Push lên GitHub (chưa làm)
```cmd
:: Tạo repo trên GitHub web hoặc:
gh repo create phuongpham3141/vkesys-orc --public --source=. --push
:: Nếu đã add remote rồi thì:
git push -u origin main
```

---

## 9. Debugging recipes

### "Job báo completed nhưng nội dung rỗng"
1. `cat logs\jobs\job_<id>.log` xem `DocumentAI response shape: text_len=X layout_blocks=Y legacy_pages=Z`
2. Nếu cả 3 = 0 → API trả rỗng (quota? content filter? bad PDF?)
3. Kiểm tra DB: `SELECT raw_response FROM ocr_results WHERE job_id=N` — nếu chỉ có row có `raw.fallback` → fallback rác từ run cũ → click "Chạy lại" sẽ tự cleanup

### "Không thấy cửa sổ console khi click retry"
1. Vào `/admin/settings` xem badge Scheduler
2. Nếu "DEAD?" hoặc "Chưa có heartbeat" → scheduler không chạy code mới → đóng cửa sổ "VIC OCR Worker", chạy lại `start.bat`
3. Click nút "Test spawn console" — nếu cửa sổ test hiện 15s → cơ chế OK, vấn đề ở scheduler
4. Xem `logs\scheduler.log` xem có dòng "Spawned runner for job X (pid=Y)" không

### "Document AI 403 CONSUMER_INVALID"
1. Chạy `scripts\verify_gcp.py` → script in ra Project ID khớp với JSON không
2. Project ID NAME ≠ ID — cái user thấy ở console URL có thể có suffix `-475822`
3. Bật Document AI API trên project: <https://console.cloud.google.com/apis/library/documentai.googleapis.com>
4. Cấp role "Document AI API User" cho Service Account

### "Werkzeug crash WinError 10038"
- Đảm bảo `FLASK_AUTO_RELOAD=false` trong `.env`
- Restart hoàn toàn (`stop.bat` → `start.bat`)

### "Gemini Test 1 trang trả 0 pages"
1. Xem log: nếu thấy `429 ResourceExhausted` → user phải nạp credits
2. Nếu API call thành công nhưng `text_len=0` → có thể content filter, đổi prompt trong `app/ocr/gemini.py:PROMPT`
3. Nếu separator `===== Trang N =====` không có → Gemini không follow prompt → đổi model hoặc prompt rõ ràng hơn

---

## 10. ESG Integration Roadmap (cho session sau)

### Bối cảnh

Project tiếp theo: hệ thống chấm điểm **ESG (Environmental, Social, Governance)** cho doanh nghiệp Việt Nam, dùng OCR project này (vkesys-orc) làm bước đầu để ingest báo cáo tài chính / báo cáo phát triển bền vững.

### Pipeline ESG end-to-end

```
1. PDF báo cáo (Vingroup, Vinamilk, FPT, ...) upload vào vkesys-orc
2. OCR engine (recommended: Document AI Layout) trích:
   - Text per page
   - Table cells (financial figures, ratios)
   - Section headings (giúp section-tagging)
3. ESG service consume từ vkesys-orc qua REST API:
   GET /api/v1/jobs/<id>/results?format=json
4. ESG service phân tích:
   - Match keywords vào criteria (Carbon emission, Diversity, Board independence...)
   - Extract numerical values từ tables (revenue, energy use, water, ...)
   - Score theo framework (GRI, SASB, TCFD, ...)
5. ESG dashboard hiển thị điểm + breakdown
```

### Cách kết nối — 2 phương án

#### Phương án A: ESG service riêng, gọi vkesys-orc qua REST API

**Ưu**: tách biệt, scale độc lập, không đụng schema OCR

**Nhược**: cần round-trip HTTP, độ trễ

```python
# ESG service code (đặt trong project khác)
import requests

VIC_OCR_BASE = "https://orc.vkesys.com/api/v1"
VIC_OCR_TOKEN = os.getenv("VIC_OCR_API_TOKEN")  # admin token từ profile page

def fetch_ocr_results(job_id: int) -> dict:
    r = requests.get(
        f"{VIC_OCR_BASE}/jobs/{job_id}/results?format=json",
        headers={"Authorization": f"Bearer {VIC_OCR_TOKEN}"},
        timeout=30,
    )
    r.raise_for_status()
    return r.json()["data"]
    # data["pages"] = list of {page_number, text_content, raw_response (with tables), ...}

def upload_pdf_for_ocr(pdf_path: str, engine: str = "document_ai") -> int:
    with open(pdf_path, "rb") as fh:
        r = requests.post(
            f"{VIC_OCR_BASE}/ocr",
            headers={"Authorization": f"Bearer {VIC_OCR_TOKEN}"},
            files={"file": fh},
            data={"engine": engine},
        )
    r.raise_for_status()
    return r.json()["data"]["id"]
```

#### Phương án B: ESG là blueprint thêm vào vkesys-orc

**Ưu**: chia sẻ DB, không round-trip, tận dụng auth/admin/UI có sẵn

**Nhược**: codebase to lên, mix concerns

```
app/
├── esg/                        # ← THÊM
│   ├── __init__.py
│   ├── routes.py               # /esg/dashboard, /esg/score/<job_id>
│   ├── models.py               # ESGScore, ESGCriterion (FK ocr_jobs)
│   ├── analyzers/              # GRI, SASB, TCFD scorers
│   └── extractors/             # Match keyword → criteria
└── templates/esg/              # esg_dashboard.html, score_breakdown.html
```

### Khuyến nghị cho ESG service

#### 1. Section tagging
Báo cáo có sections như "Báo cáo Hội đồng Quản trị", "Báo cáo Kiểm toán", "Phát triển bền vững"...
- Document AI Layout đã trả heading hierarchy → dùng `text_block.type_` (heading-1, heading-2)
- Build section tree, tag mỗi page → `OCRResult.section_path` (mới?)

Recommend: thêm column `OCRResult.section_path` (varchar) với migration:
```python
("ocr_results", "section_path", "VARCHAR(512)"),
```

Adapter Document AI parse heading → assign sections.

#### 2. Table extraction → structured rows
ESG cần dữ liệu số chính xác. `OCRResult.raw_response.tables` đã có cell matrix nhưng chưa có:
- **Table type detection** (income statement, balance sheet, energy table, ...)
- **Header normalization** (column matching: "Doanh thu thuần", "Net Revenue", ...)
- **Number parsing** ("21.431.430" với dấu chấm phân cách → int)

Recommend: thêm post-processor service:
```python
# app/services/table_postprocess.py
def classify_table(rows: list[list[str]]) -> str:
    """Return one of: 'income_statement', 'balance_sheet', 'cashflow', 'energy', 'employees', 'unknown'."""

def normalize_headers(rows: list[list[str]]) -> dict:
    """Map row[0] strings to canonical keys (revenue, cogs, opex, ...)."""

def parse_vn_number(s: str) -> Decimal | None:
    """'21.431.430' → 21431430; '(123,45)' → -123.45; '24.05% ' → 0.2405."""
```

#### 3. ESG criteria store (mới)

Schema gợi ý:

```python
class ESGCriterion(db.Model):
    __tablename__ = "esg_criteria"
    id = Column(Integer, primary_key=True)
    framework = Column(String(32))           # 'GRI', 'SASB', 'TCFD'
    code = Column(String(32))                # 'GRI 305-1', etc
    category = Column(String(16))            # 'E', 'S', 'G'
    name_vi = Column(Text)
    name_en = Column(Text)
    description = Column(Text)
    keywords = Column(JSONB)                 # match in OCR text
    table_signature = Column(JSONB)          # table classifier hints
    weight = Column(Float)

class ESGScore(db.Model):
    __tablename__ = "esg_scores"
    id = Column(Integer, primary_key=True)
    job_id = Column(FK ocr_jobs CASCADE)
    criterion_id = Column(FK esg_criteria)
    score = Column(Float)                    # 0-100
    evidence_pages = Column(JSONB)           # [page_numbers]
    extracted_value = Column(Text)           # number or quote
    confidence = Column(Float)
    notes = Column(Text)
    computed_at = Column(DateTime)

class ESGReport(db.Model):
    __tablename__ = "esg_reports"
    id = Column(Integer, primary_key=True)
    job_id = Column(FK ocr_jobs CASCADE)
    framework = Column(String(32))
    overall_score = Column(Float)
    e_score = Column(Float)
    s_score = Column(Float)
    g_score = Column(Float)
    methodology = Column(JSONB)
    generated_at = Column(DateTime)
```

#### 4. Khuyến nghị engine
Cho ESG, **Gemini Multimodal** là tối ưu nhất vì:
- Hiểu ngữ nghĩa câu chữ tiếng Việt
- Tự classify section
- Trích bảng + kèm context
- Có thể prompt: "Tìm các chỉ số ESG sau đây: ..."

Document AI Layout là phương án backup (rẻ hơn, structure tốt nhưng không hiểu ngữ nghĩa).

#### 5. Phương pháp scoring
- **Rule-based** (v1): keyword match + threshold
- **LLM-based** (v2): pass extracted text + table tới Gemini với prompt scoring rubric
- **Hybrid** (v3): rule-based điểm thô, LLM tinh chỉnh

#### 6. UX integration với vkesys-orc

Sau khi job OCR xong, hiện thêm button "Chấm điểm ESG":
```html
{% if job.status == 'completed' %}
  <a href="{{ url_for('esg.score_job', job_id=job.id) }}" class="btn btn-success">
    <i class="bi bi-graph-up me-1"></i>Chấm điểm ESG
  </a>
{% endif %}
```

Click → ESG service phân tích → render dashboard điểm.

### Dataset gợi ý
- Dùng các báo cáo phát triển bền vững / ESG đã công bố:
  - Vingroup Sustainability Report
  - Vinamilk Annual Report
  - FPT Sustainability Report
  - Petrolimex, REE, PNJ, ...
- Đã có `VIC_Baocaotaichinh_2024_Kiemtoan_Congtyme.pdf` test trong uploads/

---

## 11. Major commit milestones (21 commits, mới nhất ở đầu)

```
7414f3c Fix Gemini/Mistral test-page wasting whole-PDF tokens + 'completed but empty' lie
37a1006 Clean fallback rows on test-page so they don't pollute job detail
dc1524e Add Stop / Stop all buttons for running OCR jobs
71ac9d9 Diagnostics for 'no console window appears' — heartbeat + test spawn
ec4887f Spawn one Python console per OCR job + admin-tunable concurrency limit
6cdfc5d Atomic per-page Document AI processing + Test single page button
b067010 Move OCR work out of the Flask process — standalone worker
8a1f7b0 Parse Document AI Layout Parser response + add CSV / XLSX export
6dece9d Persist OCR pages incrementally + resume retry without redoing them
7810207 Chunk Document AI Layout requests above 30 pages
1ee2d9c Diagnose Document AI 403 errors with verify_gcp.py + better messages
2cfe871 Add 'Load models' button for Gemini settings
804f961 Add Document AI Layout Parser and Gemini multimodal engines
138969a Fix download 404 — resolve data folders to absolute paths
533d5eb Add scripts/install_poppler.ps1 — automated Poppler installer
28dae94 Add 'Run Again' button for completed/failed jobs
ecb702f Fix 'relation users does not exist' on first launch
effa20b Add scripts/install_tesseract.ps1 — automated Tesseract 5.5.0 installer
e5a824c Add start.bat / stop.bat one-click launchers
890ecd4 Default Flask to 0.0.0.0:8000 and add Google Vision setup guide
39c58f0 Initial commit: VIC OCR (vkesys-orc) — Flask multi-engine OCR platform
```

---

## 12. Câu hỏi thường gặp khi tiếp tục

**Q: Tôi nên dùng engine nào cho báo cáo tài chính Việt Nam?**
A: Document AI Layout đã verify work, recommend cho production. Gemini 2.5 Pro tốt hơn về ngữ nghĩa nhưng cần credits.

**Q: Sao file .env có ENCRYPTION_KEY mà không thấy database key encryption?**
A: Fernet encryption áp dụng cho `mistral_api_key_encrypted` và `gemini_api_key_encrypted` trong `user_ocr_configs`. Property setter/getter ở `app/models.py:UserOCRConfig`. Google credential thì lưu PATH đến file JSON (file vẫn unencrypted, được .gitignore).

**Q: Folder watcher hoạt động thế nào?**
A: Background thread trong `app/services/folder_watcher.py`. Bật bằng `FOLDER_WATCH_ENABLED=true`. Quét `WATCH_FOLDER_PATH` mỗi N giây, mỗi `.pdf` mới → INSERT OCRJob (source='folder_watch', user_id=`WATCH_FOLDER_USER_ID`) → scheduler pick up. Sau khi job submit, file PDF được move vào `WATCH_FOLDER_PROCESSED_PATH`.

**Q: Làm sao thêm engine OCR mới (ví dụ AWS Textract)?**
A:
1. Tạo `app/ocr/textract.py` extends `OCREngine`, implement `is_configured`, `ocr_image`, optional `ocr_pdf`
2. Thêm vào `app/ocr/factory.py:ENGINES` dict + `ENGINE_LABELS`
3. Thêm fields cấu hình vào `UserOCRConfig` model + `_ensure_schema` ALTER
4. Thêm tab vào `app/templates/main/settings.html` + form fields trong `app/main/forms.py`

**Q: Tại sao có cả `worker.py` và `run_one_job.py`?**
A: `worker.py` = scheduler (long-running, polls DB, spawns subprocesses). `run_one_job.py` = single-job runner (chạy 1 job rồi exit). Tách ra để mỗi job có cửa sổ console riêng + isolation tốt.

**Q: Test 1 trang trên Document AI có gửi 1 trang không hay vẫn gửi cả PDF?**
A: Document AI dùng chunk_size (default 1) → loop từng chunk, skip chunks không nằm trong target → chỉ gửi chunk chứa page target. Tiết kiệm.

**Q: Build ESG sử dụng cùng venv hay venv riêng?**
A: Khuyến nghị venv RIÊNG cho ESG service (nhiều ML deps hơn — pandas, sklearn, có thể cần torch). Connect vkesys-orc qua REST API. Dùng admin API token.

---

## 13. Liên kết tham khảo

- Spec gốc: [`Claude.md`](../Claude.md) tại project root
- Setup Google Vision: [`docs/GOOGLE_VISION_SETUP.md`](GOOGLE_VISION_SETUP.md)
- Setup Document AI + Gemini: [`docs/DOCUMENT_AI_AND_GEMINI_SETUP.md`](DOCUMENT_AI_AND_GEMINI_SETUP.md)
- Bootstrap 5.3.3 docs: <https://getbootstrap.com/docs/5.3/>
- Document AI Layout Parser: <https://cloud.google.com/document-ai/docs/layout-parse>
- Gemini API: <https://ai.google.dev/gemini-api/docs>

---

**Ngày handoff**: 2026-04-28
**Người viết**: Claude Code (Opus 4.7) cùng phuongpham3141@gmail.com
**Trạng thái**: Project tạm dừng. Sẵn sàng tiếp tục với ESG integration ở session sau.
