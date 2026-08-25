@echo off
title Distributed Job Scheduler - Full Cluster Starter
echo ========================================================
echo   Starting Distributed Job Scheduler Platform (All Services)
echo ========================================================
echo.

echo Starting Django Web Dashboard (Port 8000)...
start "DJS - Web Dashboard" cmd /k "python manage.py runserver 0.0.0.0:8000"

echo Starting Distributed Worker Node (4 Threads)...
start "DJS - Worker Node" cmd /k "python manage.py run_worker --concurrency=4"

echo Starting Central Scheduler & Zombie Reaper...
start "DJS - Central Scheduler" cmd /k "python manage.py run_scheduler --tick-interval=2.0"

echo.
echo ========================================================
echo  All services started!
echo  Open Dashboard at: http://127.0.0.1:8000/
echo ========================================================
pause

