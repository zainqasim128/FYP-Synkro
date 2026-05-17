@echo off
cd /d "%~dp0..\backend"
echo Starting Synkro Backend on http://localhost:8000 ...
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
pause
