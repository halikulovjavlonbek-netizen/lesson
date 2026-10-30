@echo off
chcp 65001 > nul
title WhatsApp Servisi

echo ════════════════════════════════════════
echo    WhatsApp WA-Platform Servisi
echo    Port: 3000
echo ════════════════════════════════════════
echo.
cd /d "%~dp0"

:RESTART
echo [%time%] WhatsApp Node.js servisi ishga tushirilmoqda...
node server.js
echo.
echo [%time%] Servis to'xtadi! 5 soniyadan keyin qayta ishga tushadi...
timeout /t 5 /nobreak
goto RESTART
