@echo off
echo Starting WhatsApp and Telegram servers...
echo.

cd /d "%~dp0"

echo [*] Starting WhatsApp server (port 3000)...
start "WhatsApp Server" cmd /k "node whatsapp_server.js"

timeout /t 2 /nobreak >nul

echo [*] Starting Telegram server (port 3001)...
start "Telegram Server" cmd /k "node telegram_server.js"

echo.
echo [OK] Servers started in separate windows
echo [*] WhatsApp: http://localhost:3000
echo [*] Telegram: http://localhost:3001
echo.
echo Press any key to exit (servers will continue running)...
pause >nul

