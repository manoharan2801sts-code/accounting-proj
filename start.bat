@echo off
title TRAVEL AGENCY - Launcher
echo ========================================================
echo       Starting TRAVEL AGENCY Accounting System
echo ========================================================

echo.
echo [1/2] Launching Django Backend at http://127.0.0.1:8000...
start "TRAVEL AGENCY Backend (Port 8000)" cmd /k "cd /d "%~dp0backend" && python manage.py runserver 127.0.0.1:8000"

timeout /t 2 /nobreak >nul

echo.
echo [2/2] Launching Frontend Server at http://127.0.0.1:8080...
start "TRAVEL AGENCY Frontend (Port 8080)" cmd /k "cd /d "%~dp0" && python -m http.server 8080 --bind 127.0.0.1"

timeout /t 2 /nobreak >nul

echo.
echo Opening TRAVEL AGENCY in default browser...
start http://localhost:8080/index.html

echo.
echo TRAVEL AGENCY is running! Close the command windows to stop the servers.
