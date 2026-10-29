@echo off
title TRAVEL AGENCY - Launcher
echo ========================================================
echo       Starting TRAVEL AGENCY Accounting System
echo ========================================================

echo.
echo [1/4] Launching Django Backend at http://127.0.0.1:8000...
start "TRAVEL AGENCY Backend (Port 8000)" cmd /k "cd /d "%~dp0backend" && python manage.py runserver 127.0.0.1:8000"

timeout /t 2 /nobreak >nul

echo.
echo [2/4] Launching Frontend Server at http://127.0.0.1:8080...
start "TRAVEL AGENCY Frontend (Port 8080)" cmd /k "cd /d "%~dp0" && python -m http.server 8080 --bind 127.0.0.1"

timeout /t 2 /nobreak >nul

echo.
echo [3/4] Launching Ticket Import Scheduler (Auto Push tickets, every 5 minutes)...
start "TRAVEL AGENCY Ticket Import Scheduler" cmd /k "cd /d "%~dp0backend" && python manage.py run_ticket_import --interval 300"

timeout /t 2 /nobreak >nul

echo.
echo [4/4] Launching Automated Database Scheduler (Airline_Agent database)...
start "TRAVEL AGENCY Automated Database Scheduler" cmd /k "cd /d "%~dp0backend" && python manage.py run_agent_db_scheduler"

echo.
echo Opening TRAVEL AGENCY in default browser...
start http://localhost:8080/index.html

echo.
echo TRAVEL AGENCY is running! Close the command windows to stop the servers.
