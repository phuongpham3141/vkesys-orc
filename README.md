# VIC OCR — Multi-Engine OCR Platform (vkesys-orc)

> Flask-based web application for OCR-ing scanned PDFs (especially Vietnamese
> financial reports) using **four OCR engines**: Google Cloud Vision, Mistral
> OCR, PaddleOCR and Tesseract. Supports web upload, REST API, and folder
> watching. Galaxy UI theme. PostgreSQL storage with full-text search.

---

## ✨ Tính năng / Features

- 🔭 **4 OCR engines**: Google Vision · Mistral OCR · PaddleOCR · Tesseract
- 📥 **3 phương thức input**:
  - Web UI (kéo-thả PDF)
  - REST API (`POST /api/v1/ocr` với Bearer token)
  - Folder watcher (auto-OCR mọi PDF trong thư mục cấu hình)
- 👤 **User management**: đăng ký, đăng nhập, vai trò admin/user, quản trị
- 🔐 **Bảo mật**: PBKDF2-SHA256 password, CSRF, Mistral key mã hoá Fernet
- 📊 **Dashboard**: thống kê job, trang đã OCR, breakdown theo engine
- 📑 **Export**: TXT / JSON / Markdown
- 🌌 **Galaxy UI**: dark space theme với glassmorphism + neon accents
- 🇻🇳 **Tiếng Việt**: UTF-8, hỗ trợ font tiếng Việt cho cả 4 engine

---

## 🏗️ Tech Stack

| Layer | Stack |
|---|---|
| Backend | Python 3.11+, Flask 3.x |
| ORM | SQLAlchemy 2.x + Flask-SQLAlchemy + Flask-Migrate |
| DB | PostgreSQL 16+ (extensions: `unaccent`, `pg_trgm`) |
| Auth | Flask-Login, Flask-WTF, werkzeug.security |
| Frontend | Bootstrap 5.3.3 + Bootstrap Icons + custom Galaxy CSS |
| Async | `concurrent.futures.ThreadPoolExecutor` (no Celery) |
| Encryption | `cryptography.fernet` cho Mistral API key |

---

## 🚀 Cài đặt nhanh / Quick start

### 1. Yêu cầu / Prerequisites (Windows)

| | |
|---|---|
| Python | **3.11+** |
| PostgreSQL | **16+** chạy ở `localhost:5432` |
| Poppler (cho `pdf2image`) | Tải từ <https://github.com/oschwartz10612/poppler-windows/releases>, giải nén, đặt đường dẫn `bin/` vào `POPPLER_PATH` |
| Tesseract (tuỳ chọn) | UB Mannheim build <https://github.com/UB-Mannheim/tesseract/wiki> + Vietnamese tessdata. Hoặc auto-install qua `scripts/install_tesseract.ps1` |
| Google Cloud (tuỳ chọn) | Service Account JSON đặt trong `credentials/` |
| Mistral API key (tuỳ chọn) | <https://console.mistral.ai> |

### 2. Cài đặt / Install

```powershell
# Clone & vào thư mục
git clone https://github.com/<your-user>/vkesys-orc.git
cd vkesys-orc

# Tạo venv
python -m venv venv
.\venv\Scripts\activate

# Install
pip install -r requirements.txt

# Copy .env.example -> .env
copy .env.example .env

# Sinh SECRET_KEY và ENCRYPTION_KEY
python -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"
python -c "from cryptography.fernet import Fernet; print('ENCRYPTION_KEY=' + Fernet.generate_key().decode())"
# Dán hai giá trị trên vào file .env
```

### 3. Tạo DB và migrations

Mở `psql` hoặc pgAdmin:

```sql
CREATE DATABASE vic_ocr;
\c vic_ocr
CREATE EXTENSION IF NOT EXISTS unaccent;
CREATE EXTENSION IF NOT EXISTS pg_trgm;
```

```powershell
$env:FLASK_APP="run.py"
flask db init
flask db migrate -m "initial schema"
flask db upgrade
```

### 4. Chạy

```powershell
python run.py
# Mở http://localhost:8000
# Đăng nhập: admin / admin123 (đổi mật khẩu ngay sau lần đầu)
```

### 🚀 One-click launcher (Windows)

Đơn giản hơn: **double-click `start.bat`**. Script sẽ tự động:

1. Tạo `venv\` nếu chưa có
2. Cài đặt `requirements.txt`
3. Sinh `.env` (random `SECRET_KEY` + `ENCRYPTION_KEY`) nếu chưa có
4. Tạo database PostgreSQL `vic_ocr` + extensions `unaccent`, `pg_trgm`
5. Chạy migrations Alembic
6. Khởi động Flask trên `http://0.0.0.0:8000`

Để dừng: nhấn `Ctrl+C` trong cửa sổ console, hoặc double-click `stop.bat`.

---

## 📡 REST API

Mọi endpoint cần header: `Authorization: Bearer <api_token>`
(lấy từ trang **Hồ sơ → API Token**).

| Method | Path | Mô tả |
|---|---|---|
| GET | `/api/v1/engines` | Liệt kê engine + trạng thái cấu hình |
| POST | `/api/v1/ocr` | Form-data: `file` (PDF), `engine`. Tạo job mới. |
| GET | `/api/v1/jobs?status=&engine=&limit=&offset=` | Liệt kê job |
| GET | `/api/v1/jobs/<id>` | Lấy thông tin 1 job |
| GET | `/api/v1/jobs/<id>/results?format=json\|text\|markdown` | Lấy toàn bộ kết quả |
| GET | `/api/v1/jobs/<id>/results/<page>` | Lấy 1 trang |
| DELETE | `/api/v1/jobs/<id>` | Xoá job + file + kết quả |

**Response envelope**:

```json
{ "success": true, "data": {...}, "error": null, "meta": {...} }
```

Lỗi:

```json
{ "success": false, "data": null,
  "error": { "code": "INVALID_FILE", "message": "..." } }
```

Rate limit mặc định: **60 requests / phút** (chỉnh trong `.env`).

### Ví dụ cURL

```bash
curl -X POST http://localhost:5000/api/v1/ocr \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -F "file=@invoice.pdf" \
  -F "engine=tesseract"
```

---

## 📂 Folder Watcher

Bật trong `.env`:

```ini
FOLDER_WATCH_ENABLED=true
WATCH_FOLDER_PATH=./watch_folder
WATCH_FOLDER_PROCESSED_PATH=./watch_folder_processed
WATCH_FOLDER_USER_ID=1            # job sẽ thuộc về user_id này
WATCH_FOLDER_ENGINE=tesseract
WATCH_INTERVAL_SECONDS=30
```

Khi server chạy, thread nền sẽ:
1. Quét `WATCH_FOLDER_PATH` mỗi `WATCH_INTERVAL_SECONDS` giây
2. Với mỗi `*.pdf` mới: tạo `OCRJob (source='folder_watch')`, submit vào pool
3. Sau khi job tạo xong, chuyển PDF sang `WATCH_FOLDER_PROCESSED_PATH`
4. Log vào `logs/folder_watcher.log`

---

## 🔐 Bảo mật

- Password: `pbkdf2:sha256` qua `werkzeug.security`
- CSRF: Flask-WTF (mọi form HTML)
- API token: 64 ký tự URL-safe random, có thể tái tạo
- Mistral API key: mã hoá Fernet trước khi lưu DB
- File upload: validate đuôi `.pdf`, sanitize filename, giới hạn `MAX_UPLOAD_MB`
- Session cookie: `HttpOnly`, `SameSite=Lax`, `Secure=True` ở production

---

## 📦 Cấu trúc dự án

```
vkesys-orc/
├── app/
│   ├── __init__.py          # Flask app factory
│   ├── config.py            # Dev/Prod config
│   ├── extensions.py        # db, login, migrate, csrf, limiter
│   ├── models.py            # User, UserOCRConfig, OCRJob, OCRResult
│   ├── auth/                # Đăng ký/đăng nhập/hồ sơ
│   ├── admin/               # Quản trị user (admin-only)
│   ├── main/                # Dashboard, upload, jobs, settings
│   ├── api/                 # REST API + token auth
│   ├── ocr/                 # 4 engine adapters + factory + pdf_utils
│   ├── services/            # ocr_service (ThreadPool), folder_watcher
│   ├── static/              # galaxy.css, app.js, upload.js
│   └── templates/           # Jinja2 templates với Galaxy UI
├── migrations/              # Alembic
├── uploads/                 # PDF người dùng tải lên (gitignored)
├── outputs/                 # File export (gitignored)
├── watch_folder/            # Input cho folder watcher (gitignored)
├── credentials/             # Google service account JSON (gitignored)
├── logs/                    # app.log + folder_watcher.log (gitignored)
├── run.py                   # Entry point dev
├── wsgi.py                  # Entry point production
├── requirements.txt
├── .env.example             # Template config
└── README.md
```

---

## 🧭 Build order (tham khảo cho contributor)

1. ✅ Skeleton + Galaxy UI base
2. ✅ Models + migrations + bootstrap admin
3. ✅ Auth (register/login/logout/profile)
4. ✅ Admin user management
5. ✅ OCR adapters (base/factory/pdf_utils + 4 engines)
6. ✅ Upload + ThreadPool processing + status polling
7. ✅ Settings (per-user encrypted credentials)
8. ✅ REST API + token auth + rate limiting
9. ✅ Folder watcher
10. 🚧 Tests, CI, Docker

---

## ⚠️ Troubleshooting

| Lỗi | Cách xử lý |
|---|---|
| `pdf2image.exceptions.PDFInfoNotInstalledError` | Cài Poppler, set `POPPLER_PATH` trong `.env` |
| Tesseract không tìm thấy | Kiểm tra `TESSERACT_CMD` trỏ tới `tesseract.exe` |
| Tiếng Việt OCR sai | Cài Vietnamese tessdata (`vie.traineddata`) |
| `paddleocr` lần đầu chậm | Đang tải mô hình ~500MB, đợi xong |
| `psycopg.OperationalError` | Kiểm tra PostgreSQL chạy + `DATABASE_URL` đúng |
| Mistral encrypt báo lỗi | Kiểm tra `ENCRYPTION_KEY` là Fernet key hợp lệ |

---

## 📝 License

MIT — sử dụng tự do, không bảo hành.

---

## 🙋 Liên hệ

Repo: <https://github.com/your-username/vkesys-orc>

Built with ❤️ + Flask · Galaxy UI · Vietnamese ❤️ OCR
