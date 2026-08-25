# Distributed Job Scheduler - PowerShell Launcher
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "  Starting Distributed Job Scheduler Platform" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan

# 1. Start Web Server
Start-Process powershell -ArgumentList "-NoExit", "-Command", "python manage.py runserver 0.0.0.0:8000"

# 2. Start Worker Daemon
Start-Process powershell -ArgumentList "-NoExit", "-Command", "python manage.py run_worker --concurrency=4"

# 3. Start Scheduler Daemon
Start-Process powershell -ArgumentList "-NoExit", "-Command", "python manage.py run_scheduler --tick-interval=2.0"

Write-Host "`nAll 3 services successfully started in separate background windows!" -ForegroundColor Green
Write-Host "Access Web Dashboard: http://127.0.0.1:8000/" -ForegroundColor Yellow

