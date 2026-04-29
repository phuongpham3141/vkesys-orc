@echo off
REM =====================================================================
REM  VIC OCR (vkesys-orc) — One-click launcher
REM  Tu dong: tao venv, cai pip deps, sinh .env, migrate DB, chay Flask
REM =====================================================================
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"

echo.
echo ============================================================
echo   VIC OCR  -  Galaxy OCR Platform
echo ============================================================
echo.

REM --- 1. Tim Python ---------------------------------------------------
set "PYEXE="
where py >nul 2>nul && set "PYEXE=py -3"
if "!PYEXE!"=="" where python >nul 2>nul && set "PYEXE=python"
if "!PYEXE!"=="" (
    echo [LOI] Khong tim thay Python. Vui long cai Python 3.11+ truoc:
    echo       https://www.python.org/downloads/
    echo       Nho tick "Add Python to PATH" khi cai.
    pause
    exit /b 1
)
echo [OK] Python: !PYEXE!

REM --- 2. Tao venv neu chua co -----------------------------------------
if not exist "venv\Scripts\python.exe" (
    echo [..] Tao virtual environment...
    !PYEXE! -m venv venv
    if errorlevel 1 (
        echo [LOI] Tao venv that bai.
        pause
        exit /b 1
    )
    echo [OK] Da tao venv\
) else (
    echo [OK] venv\ da ton tai
)

set "VENV_PY=%CD%\venv\Scripts\python.exe"
set "VENV_PIP=%CD%\venv\Scripts\pip.exe"

REM --- 3. Cai dat dependencies (chi khi can) ---------------------------
if not exist "venv\.deps_installed" (
    echo [..] Cai dependencies tu requirements.txt - co the mat vai phut...
    "!VENV_PY!" -m pip install --upgrade pip
    "!VENV_PIP!" install -r requirements.txt
    if errorlevel 1 (
        echo [LOI] Cai dat that bai. Kiem tra ket noi mang.
        pause
        exit /b 1
    )
    echo done > "venv\.deps_installed"
    echo [OK] Da cai dependencies
) else (
    echo [OK] Dependencies da san
)

REM --- 4. Tao .env neu chua co -----------------------------------------
if not exist ".env" (
    echo [..] Tao .env tu .env.example...
    copy /y ".env.example" ".env" >nul

    for /f "delims=" %%a in ('"!VENV_PY!" -c "import secrets; print(secrets.token_hex(32))"') do set "GEN_SECRET=%%a"
    for /f "delims=" %%a in ('"!VENV_PY!" -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"') do set "GEN_FERNET=%%a"

    "!VENV_PY!" -c "import pathlib,re; p=pathlib.Path('.env'); t=p.read_text(encoding='utf-8'); t=re.sub(r'^SECRET_KEY=.*$', 'SECRET_KEY=!GEN_SECRET!', t, flags=re.M); t=re.sub(r'^ENCRYPTION_KEY=.*$', 'ENCRYPTION_KEY=!GEN_FERNET!', t, flags=re.M); p.write_text(t, encoding='utf-8')"

    echo [OK] Da tao .env voi SECRET_KEY va ENCRYPTION_KEY moi
    echo      Mo .env de chinh DATABASE_URL, MISTRAL_API_KEY, ... neu can
) else (
    echo [OK] .env da ton tai
)

REM --- 5. Tao thu muc data ---------------------------------------------
for %%d in (uploads outputs watch_folder watch_folder_processed credentials logs) do (
    if not exist "%%d" mkdir "%%d"
)
echo [OK] Cac thu muc data san sang

REM --- 6a. Tao database va extensions (idempotent) --------------------
echo [..] Kiem tra/Tao PostgreSQL database + extensions...
"!VENV_PY!" scripts\init_db.py
if errorlevel 1 (
    echo [LOI] Khong the chuan bi database. Kiem tra:
    echo       - PostgreSQL dang chay tren localhost:5432
    echo       - DATABASE_URL trong .env dung user/password
    pause
    exit /b 1
)

REM --- 6b. Database migrations ----------------------------------------
set "FLASK_APP=run.py"
if not exist "migrations" (
    echo [..] Khoi tao migrations Alembic...
    "!VENV_PY!" -m flask db init
    if errorlevel 1 (
        echo [LOI] flask db init that bai.
        pause
        exit /b 1
    )
)

echo [..] Tao migration moi (neu co thay doi schema)...
"!VENV_PY!" -m flask db migrate -m "auto" 2>nul

echo [..] Apply migrations (db upgrade)...
"!VENV_PY!" -m flask db upgrade
if errorlevel 1 (
    echo [LOI] Migration that bai. Kiem tra:
    echo       1. PostgreSQL dang chay tren localhost:5432
    echo       2. DATABASE_URL trong .env dung dinh dang
    echo       3. Database 'vic_ocr' da duoc tao:
    echo          psql -U postgres -c "CREATE DATABASE vic_ocr;"
    echo          psql -U postgres -d vic_ocr -c "CREATE EXTENSION IF NOT EXISTS unaccent;"
    echo          psql -U postgres -d vic_ocr -c "CREATE EXTENSION IF NOT EXISTS pg_trgm;"
    pause
    exit /b 1
)

REM --- 7. Khoi dong Flask ----------------------------------------------
echo.
echo ============================================================
echo   Khoi dong Flask tren http://0.0.0.0:8000
echo   Mo trinh duyet: http://localhost:8000
echo   Tai khoan mac dinh: admin / admin123
echo   Nhan Ctrl+C de dung server
echo ============================================================
echo.

"!VENV_PY!" run.py

endlocal
pause
