@echo off
REM =====================================================================
REM  VIC OCR (vkesys-orc) - One-click launcher
REM  Tu dong: tao venv, cai pip deps, sinh .env, migrate DB,
REM           spawn worker trong cua so rieng, chay Flask web
REM =====================================================================
setlocal enabledelayedexpansion
chcp 65001 >nul
cd /d "%~dp0"
title VIC OCR Web

echo.
echo ============================================================
echo   VIC OCR  -  Galaxy OCR Platform
echo ============================================================
echo.

REM --- 0. Bao ve khoi double-launch -----------------------------------
REM Neu port 8000 dang listen, Flask da chay -> thoat luon thay vi tao xung dot.
netstat -ano | findstr ":8000" | findstr "LISTENING" >nul 2>nul
if %errorlevel%==0 (
    echo [DA CHAY] VIC OCR dang chay tren cong 8000.
    echo           Neu can restart: chay stop.bat truoc, roi start.bat.
    echo           Mo trinh duyet: http://localhost:8000
    echo.
    pause
    exit /b 0
)

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
for %%d in (uploads outputs watch_folder watch_folder_processed credentials logs logs\jobs) do (
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

REM --- 6b. Database migrations + ensure schema ------------------------
set "FLASK_APP=run.py"
if not exist "migrations" (
    "!VENV_PY!" -m flask db init >nul 2>nul
)
"!VENV_PY!" -m flask db migrate -m "auto" >nul 2>nul
"!VENV_PY!" -m flask db upgrade >nul 2>nul
echo [..] Bao dam tat ca bang ton tai (fallback create_all)...
"!VENV_PY!" -c "from app import create_app; from app.extensions import db; app=create_app(); ctx=app.app_context(); ctx.push(); db.create_all(); print('[OK] Tables ensured')"

REM --- 7a. Spawn OCR Worker scheduler trong cua so rieng --------------
echo.
echo [..] Spawn cua so VIC OCR Worker scheduler...
start "VIC OCR Worker" /D "%~dp0" cmd /k ""!VENV_PY!" worker.py"

REM Cho 2s de cua so worker thuc su xuat hien truoc khi tiep tuc
ping -n 3 127.0.0.1 >nul

REM --- 7b. Khoi dong Flask ---------------------------------------------
echo.
echo ============================================================
echo   Web:    http://localhost:8000  (cua so nay)
echo   Worker: cua so "VIC OCR Worker" rieng (poll DB, xu ly OCR)
echo   Tai khoan mac dinh: admin / admin123
echo   Stop tat ca: chay stop.bat
echo ============================================================
echo.

"!VENV_PY!" run.py

endlocal
pause
