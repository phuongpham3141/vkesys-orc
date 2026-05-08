@echo off
REM ============================================================
REM  VIC OCR - Go bo watchdog
REM ============================================================
cd /d "%~dp0"

net session >nul 2>nul
if %errorlevel% neq 0 (
    echo [..] Can quyen Administrator. Yeu cau elevate...
    powershell -Command "Start-Process cmd -ArgumentList '/c \"%~f0\"' -Verb RunAs"
    exit /b 0
)

echo ============================================================
echo   Go bo VIC OCR Watchdog
echo ============================================================
powershell -ExecutionPolicy Bypass -File "%~dp0scripts\uninstall_watchdog.ps1"

echo.
pause
