@echo off
REM Dung server VIC OCR (kill tien trinh Python tren cong 8000)
echo Dang tim tien trinh tren cong 8000...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8000" ^| findstr "LISTENING"') do (
    echo Kill PID %%a
    taskkill /F /PID %%a 2>nul
)
echo Da dung server.
pause
