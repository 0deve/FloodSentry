@echo off
echo ======================================================
echo     FloodSentry - EU Digital Twin Start Script
echo ======================================================
echo.

:: 1. Backend Training & Data
cd backend
echo [1/3] Step 1: Training XGBoost Multi-Hazard Model...
echo This uses synthetic EMS ground truth and historical features.
call venv\Scripts\python train_xgboost.py
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Training failed! Check if dependencies are installed.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [1.5/3] Step 1.5: Importing All Europe NUTS-3 Regions...
call venv\Scripts\python import_europe.py


echo.
echo [2/3] Step 2: Ingesting Real Copernicus/Meteo Data...
echo Fetching latest 7-day forecast and running XGBoost predictions.
call venv\Scripts\python populate_predictions.py
if %ERRORLEVEL% NEQ 0 (
    echo [ERROR] Data ingestion failed! Check your internet connection.
    pause
    exit /b %ERRORLEVEL%
)

echo.
echo [3/3] Step 3: Starting Backend API...
start "FloodSentry Backend" cmd /k "venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port 8000"

:: 2. Frontend
echo.
cd ..\frontend
echo [4/4] Step 4: Starting Frontend App...
start "FloodSentry Frontend" cmd /k "npm run dev"

echo.
echo ======================================================
echo [SUCCESS] FloodSentry System Launched!
echo.
echo - Backend: http://127.0.0.1:8000
echo - Frontend: Check the second terminal for URL
echo - Dashboard: http://localhost:5173 (usually)
echo ======================================================
echo.
pause
