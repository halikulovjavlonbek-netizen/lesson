@echo off
chcp 65001 > nul
title O'quv Markazi - Barcha Servislar

echo ╔════════════════════════════════════════════════╗
echo ║   O'QUV MARKAZI - SERVISLARNI ISHGA TUSHIRISH  ║
echo ╚════════════════════════════════════════════════╝
echo.

REM --- WhatsApp Node.js Servisini alohida oynada ishga tushirish ---
echo [1/2] WhatsApp Node.js servisi ishga tushirilmoqda (port 3000)...
start "WhatsApp WA-Platform (port 3000)" cmd /k "cd /d "%~dp0wa-platform" && echo WhatsApp servisi yuklanmoqda... && npm start"

REM --- 2 soniya kutish ---
timeout /t 2 /nobreak > nul

REM --- Django servisini ishga tushirish ---
echo [2/2] Django veb-server ishga tushirilmoqda (port 8000)...
start "Django O'quv Markazi (port 8000)" cmd /k "cd /d "%~dp0" && echo Django server yuklanmoqda... && python manage.py runserver"

echo.
echo ✅ Ikkala servis ham alohida oynalarda ishga tushdi!
echo.
echo   WhatsApp: http://localhost:3000
echo   Django:   http://localhost:8000
echo   Panel:    http://localhost:8000/dashboard/
echo.
echo Bu oynani yopishingiz mumkin.
pause
