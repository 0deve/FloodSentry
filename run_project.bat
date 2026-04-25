@echo off
echo ==========================================
echo    FloodSentry - Starting All Services
echo ==========================================

:: Start Backend in a new window
echo Starting Backend on port 8001...
start "FloodSentry Backend" cmd /k "cd backend && python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8001"

:: Wait a few seconds for backend to initialize
timeout /t 3 /nobreak > nul

:: Start Frontend in a new window
echo Starting Frontend...
start "FloodSentry Frontend" cmd /k "cd frontend && npm run dev"

echo.
echo ==========================================
echo    All services are starting!
echo    Backend: http://127.0.0.1:8001
echo    Frontend: http://localhost:5173
echo ==========================================
pause
