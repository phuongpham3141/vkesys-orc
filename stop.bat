@echo off
REM Dung server VIC OCR + worker
echo Dang tim tien trinh tren cong 8000 (web)...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo Kill PID %%a
    taskkill /F /PID %%a 2>nul
)
echo.
echo Dang tim cua so VIC OCR Worker...
taskkill /F /FI "WINDOWTITLE eq VIC OCR Worker*" 2>nul
echo.
echo Da dung web va worker.
pause
