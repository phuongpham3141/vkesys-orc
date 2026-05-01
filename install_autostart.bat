@echo off
REM ============================================================
REM  VIC OCR - Cai autostart vao Task Scheduler
REM  Tu dong yeu cau quyen Administrator neu chua co
REM ============================================================
cd /d "%~dp0"

REM Kiem tra quyen admin, neu khong thi self-elevate
net session >nul 2>nul
if %errorlevel% neq 0 (
    echo [..] Can quyen Administrator. Dang yeu cau elevate...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"%~f0\"' -Verb RunAs"
    exit /b 0
)

echo ============================================================
echo   Cai VIC OCR auto-start
echo ============================================================
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\install_autostart.ps1"

echo.
pause
