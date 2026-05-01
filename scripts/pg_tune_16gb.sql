-- VIC OCR — PostgreSQL tuning for VPS 16 GB RAM / 12 vCPU
--
-- Chay sau khi VPS da duoc nang cap len 16GB RAM:
--   psql -U postgres -f scripts\pg_tune_16gb.sql
--
-- Sau do RESTART postgresql service de shared_buffers + max_connections
-- co hieu luc:
--   net stop postgresql-x64-18 && net start postgresql-x64-18
--
-- Verify:
--   SELECT name, setting, unit FROM pg_settings
--    WHERE name IN ('shared_buffers','effective_cache_size','max_connections',
--                   'work_mem','maintenance_work_mem');

-- Memory tuning (target 16GB RAM)
ALTER SYSTEM SET shared_buffers = '4GB';                    -- 25% RAM
ALTER SYSTEM SET effective_cache_size = '12GB';             -- 75% RAM (hint)
ALTER SYSTEM SET work_mem = '16MB';                         -- per connection sort
ALTER SYSTEM SET maintenance_work_mem = '512MB';
ALTER SYSTEM SET wal_buffers = '16MB';

-- Connection cap (du cho 10 worker x 5 conn + 60 web pool + 5 scheduler + buffer)
ALTER SYSTEM SET max_connections = '300';

-- Parallel query (12 vCPU)
ALTER SYSTEM SET max_worker_processes = '12';
ALTER SYSTEM SET max_parallel_workers = '12';
ALTER SYSTEM SET max_parallel_workers_per_gather = '4';
ALTER SYSTEM SET max_parallel_maintenance_workers = '4';

-- Disk tuning (assumed SSD/NVMe)
ALTER SYSTEM SET random_page_cost = '1.1';
ALTER SYSTEM SET effective_io_concurrency = '200';
ALTER SYSTEM SET checkpoint_completion_target = '0.9';

-- Logging slow queries (>1s) for diagnostics
ALTER SYSTEM SET log_min_duration_statement = '1000';

-- Reload most settings without restart (shared_buffers + max_connections still need restart)
SELECT pg_reload_conf();

-- Echo results so you can verify
SELECT name, setting, unit
  FROM pg_settings
 WHERE name IN (
     'shared_buffers', 'effective_cache_size', 'max_connections',
     'work_mem', 'maintenance_work_mem',
     'max_worker_processes', 'max_parallel_workers'
 )
 ORDER BY name;
