@echo off
echo Starting Synkro Backend...
start "Synkro Backend" cmd /k "cd /d "%~dp0..\backend" && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"

echo Starting Synkro Frontend...
start "Synkro Frontend" cmd /k "cd /d "%~dp0..\frontend" && npm run dev"

echo.
echo Both servers launching in separate windows.
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:3000
echo   API Docs: http://localhost:8000/api/docs
echo.
pause
