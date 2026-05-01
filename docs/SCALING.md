# Scaling VIC OCR — DB pool, PostgreSQL, VPS sizing

> **TL;DR** — Trước khi nâng `DB_POOL_SIZE=150`, cần (1) tăng PostgreSQL
> `max_connections`, (2) cấp đủ RAM, (3) cân nhắc PgBouncer thay vì pool to.

## 1. Bài toán: Pool size bao nhiêu là đủ?

### Pool size = số kết nối **idle** + **active** mà Flask giữ

Flask web (waitress) xử lý 1 request mỗi thread. Mỗi request chỉ giữ 1 connection
**trong lúc đang query** (vài ms). Sau query xong, connection trả về pool.

→ Với `WAITRESS_THREADS=16`, **tối đa 16 query đồng thời** → cần ~16 connections.

`pool_size=10 + max_overflow=20 = 30` cho web là **đủ rộng rãi**.

Bumping lên 150 chỉ có ý nghĩa khi:
- Mở rộng waitress threads lên 100+ (cần CPU mạnh)
- Chạy nhiều Flask process song song (gunicorn/uwsgi multi-worker)

### Tổng connection thực tế

VIC OCR có nhiều process cùng nói chuyện với PostgreSQL:

```
┌────────────────────────────────────────┐
│ Flask web (waitress)                   │  pool_size + max_overflow
│  - serve UI/API                        │  = 10 + 20 = 30 max
│  - status polling                      │
└────────────────────────────────────────┘
┌────────────────────────────────────────┐
│ Scheduler (worker.py)                  │  ~5 connections
│  - claim/dispatch jobs                 │
│  - heartbeat updates                   │
└────────────────────────────────────────┘
┌────────────────────────────────────────┐
│ Subprocess workers × N                 │  N × 5 connections
│  - run_one_job.py                      │  (tiny pool 2+3)
│  - INSERT page kết quả                 │
└────────────────────────────────────────┘
                 ↓
┌────────────────────────────────────────┐
│ PostgreSQL                             │
│  max_connections = ???                 │
└────────────────────────────────────────┘
```

| MAX_CONCURRENT_WORKERS | DB_POOL_SIZE | Total | Min PG max_connections |
|---|---|---|---|
| 2 (default) | 10 + 20 | 45 | 100 ✓ default OK |
| 5 | 10 + 20 | 60 | 100 ✓ |
| 10 | 10 + 20 | 85 | 100 ⚠️ tight |
| 20 | 10 + 20 | 135 | 200 |
| 20 | 50 + 100 | 255 | 300 |
| 20 | 100 + 50 | 255 | 300 |
| 20 (default) | 150 + 50 | 305 | 350+ |

## 2. Cấu hình PostgreSQL

### 2.1 Tăng `max_connections`

Sửa `postgresql.conf` (Windows: `C:\Program Files\PostgreSQL\16\data\postgresql.conf`):

```conf
# Trước
max_connections = 100

# Sau (tùy nhu cầu — KHÔNG vượt 500 trừ khi có lý do)
max_connections = 300
```

### 2.2 RAM tuning đi kèm

Mỗi connection dùng ~5-10MB RAM (work_mem + temp_buffers + per-process overhead).
300 connections = ~3GB chỉ để giữ connections idle.

Cấu hình tối thiểu cho PostgreSQL trên VPS:

```conf
# Cho VPS RAM 8GB (recommended cho 300 connections)
shared_buffers = 2GB              # 25% RAM
effective_cache_size = 6GB        # 75% RAM (hint)
work_mem = 8MB                    # Per connection. 300 × 8MB = 2.4GB peak
maintenance_work_mem = 256MB
wal_buffers = 16MB
checkpoint_completion_target = 0.9
random_page_cost = 1.1            # SSD
effective_io_concurrency = 200    # SSD
max_worker_processes = 8
max_parallel_workers = 8

max_connections = 300
```

**Khởi động lại PostgreSQL** sau khi sửa:
```cmd
:: Windows
net stop postgresql-x64-16
net start postgresql-x64-16

:: Linux
sudo systemctl restart postgresql
```

### 2.3 Verify

```sql
SHOW max_connections;
SELECT count(*) FROM pg_stat_activity;
SELECT count(*) FROM pg_stat_activity WHERE state = 'active';
```

## 3. VPS spec recommendations

| Tải dự kiến | Concurrent jobs | RAM | CPU | Disk |
|---|---|---|---|---|
| Cá nhân (1-2 user) | 2-3 | 4 GB | 2 vCPU | 50 GB SSD |
| Team nhỏ (5-10 user) | 5-10 | 8 GB | 4 vCPU | 100 GB SSD |
| Production thật | 20+ | 16 GB | 8 vCPU | 200 GB SSD NVMe |

**Phân bổ RAM ý kiến tham khảo (VPS 8GB)**:
- PostgreSQL: 3 GB (shared_buffers + connections)
- Flask + waitress: 500 MB
- Scheduler: 100 MB
- 10 subprocess workers chạy song song × 200-500MB mỗi cái = 2-5 GB
- OS + cache: 1.5 GB

→ Subprocess là phần "nặng" nhất. Document AI tốn RAM khi parse big PDF response, Gemini cũng tương tự. Tăng `MAX_CONCURRENT_WORKERS` cẩn thận — mỗi tăng 1 đơn vị tốn thêm ~300-500 MB RAM.

### CPU

OCR subprocess phần lớn idle vì đợi cloud API trả về. Không cần CPU cao.
4 vCPU đủ cho ~10-20 concurrent workers.

Tesseract / PaddleOCR là local CPU-bound — cần nhiều CPU hơn.

## 4. Lựa chọn nâng cao: PgBouncer (connection pooler)

Khi cần > 50 connection từ Flask, **PgBouncer** giảm load PostgreSQL đáng kể:

```
Flask (pool 100) ──┐
Worker × 20 ───────┼──► PgBouncer (transaction pool, 10 actual) ──► PostgreSQL
Scheduler ─────────┘
```

PgBouncer giữ 100 logical connections cho app nhưng chỉ tốn 10 connections thật ở PG. RAM giảm 90%.

### Cài PgBouncer trên Windows

1. Tải <https://www.pgbouncer.org/downloads/>
2. Tạo `pgbouncer.ini`:
   ```ini
   [databases]
   vic_ocr = host=127.0.0.1 port=5432 dbname=vic_ocr

   [pgbouncer]
   listen_addr = 127.0.0.1
   listen_port = 6432
   auth_type = md5
   auth_file = userlist.txt
   pool_mode = transaction
   max_client_conn = 200
   default_pool_size = 20
   server_idle_timeout = 60
   ```
3. Đổi `DATABASE_URL` trong `.env`:
   ```
   DATABASE_URL=postgresql+psycopg://postgres:Phuong2606@localhost:6432/vic_ocr
   ```

> Lưu ý: `pool_mode=transaction` không support `LISTEN/NOTIFY` hoặc prepared
> statements. SQLAlchemy 2.x mặc định không dùng prepared, OK.

## 5. Ví dụ thực tế

### Trường hợp: 1 admin + 5 user upload báo cáo tài chính

- `MAX_CONCURRENT_WORKERS = 5`
- `DB_POOL_SIZE = 15`, `DB_MAX_OVERFLOW = 25`
- Total: 15+25 + 5×5 + 5 = ~75 connections
- PG: `max_connections = 100` (default) đủ
- VPS: 4 GB RAM, 2 vCPU OK

### Trường hợp: tổ chức 50 user, vài chục PDF/ngày

- `MAX_CONCURRENT_WORKERS = 20`
- `WAITRESS_THREADS = 32`
- `DB_POOL_SIZE = 30`, `DB_MAX_OVERFLOW = 60`
- Total: 30+60 + 20×5 + 5 = ~195 connections
- PG: `max_connections = 250`, `shared_buffers = 4 GB`
- VPS: 16 GB RAM, 8 vCPU
- Khuyến nghị PgBouncer

### Trường hợp: bạn muốn `DB_POOL_SIZE = 150`

- Total: 150+50 + 20×5 + 5 = ~305 connections
- PG: `max_connections = 350`, `shared_buffers = 4-6 GB`
- VPS: 16 GB RAM minimum
- **Lý do hợp lý**: chạy nhiều Flask process song song (gunicorn -w 4), mỗi process giữ pool riêng. Hoặc app có nhiều endpoint long-polling.
- **Nếu chỉ 1 Flask process**: 150 là quá thừa, lãng phí RAM. Bumping `WAITRESS_THREADS` là cách đúng.

## 6. Cách áp dụng

```cmd
:: Sửa .env
DB_POOL_SIZE=30
DB_MAX_OVERFLOW=60
WAITRESS_THREADS=32

:: Sửa PostgreSQL (cần admin)
:: Edit postgresql.conf -> max_connections=200
net stop postgresql-x64-16
net start postgresql-x64-16

:: Restart Flask + scheduler
stop.bat
start.bat
```

Verify:
```sql
SHOW max_connections;
SELECT count(*) FROM pg_stat_activity;
```

Hoặc xem trong Flask `/admin/settings` (sẽ thêm endpoint pg_stat sau).

## 7. Khuyến nghị cuối cùng

**Đừng bump pool_size cao hơn cần thiết**:
- Mỗi connection idle = 5-10 MB RAM
- Pool to nhưng không dùng = lãng phí
- App đơn process → `WAITRESS_THREADS × 2` là đủ

**Trước khi tăng pool, kiểm tra**:
1. `logs/app.log` có nhiều `SLOW request` không? Nếu có → bottleneck thật
2. `SELECT count(*) FROM pg_stat_activity` lúc cao điểm có gần `max_connections` không?
3. `pg_stat_database` xem rollback rate / waiting connections

**Quy tắc cấp tiến**:
- Chỉ tăng pool khi đo được vấn đề thực tế
- Tăng PostgreSQL `max_connections` LUÔN cùng lúc
- Tăng RAM song song
- Cân nhắc PgBouncer trước khi vượt 50 pool size
