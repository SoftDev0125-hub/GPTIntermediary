@echo off
REM Run Gmail OAuth - no Python required. Put .env next to this file (or copy from .env.example).
cd /d "%~dp0"
if exist "get_gmail_token.exe" (
    get_gmail_token.exe
) else (
    echo get_gmail_token.exe not found. Run build/build.py first.
)
if errorlevel 1 pause
