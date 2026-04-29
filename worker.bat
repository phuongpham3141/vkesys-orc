@echo off
REM ============================================================
REM VIC OCR worker — chay cac job OCR doc lap voi web Flask
REM ============================================================
chcp 65001 >nul
cd /d "%~dp0"
title VIC OCR Worker

if not exist "venv\Scripts\python.exe" (
    echo [LOI] Chua co venv. Chay start.bat truoc de cai dat.
    pause
    exit /b 1
)

echo ============================================================
echo   VIC OCR Worker - poll DB & xu ly OCR jobs
echo   Log: logs\worker.log
echo   Stop bang Ctrl+C
echo ============================================================
echo.

venv\Scripts\python.exe worker.py

echo.
echo Worker da dung. Nhan Enter de dong.
pause
