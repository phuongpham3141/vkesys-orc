@echo off
REM ===============================================================
REM  VIC OCR - Cai watchdog (chay moi 15 phut, tu kiem tra + restart)
REM  Tu dong yeu cau Administrator neu chua co
REM ===============================================================
cd /d "%~dp0"

net session >nul 2>nul
if %errorlevel% neq 0 (
    echo [..] Can quyen Administrator. Yeu cau elevate...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"%~f0\"' -Verb RunAs"
    exit /b 0
)

echo ============================================================
echo   Cai VIC OCR Watchdog
echo ============================================================
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\install_watchdog.ps1"

echo.
pause
