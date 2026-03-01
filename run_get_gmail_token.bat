@echo off
REM Run Gmail OAuth token script. Uses get_gmail_token.exe if built (no Python needed); else uses Python.
cd /d "%~dp0"
if exist "dist\get_gmail_token.exe" (
    dist\get_gmail_token.exe
) else if exist "get_gmail_token.exe" (
    get_gmail_token.exe
) else (
    python backend\python\get_gmail_token.py
)
if errorlevel 1 (
    echo.
    pause
    exit /b 1
)
echo.
pause
