@echo off
setlocal enabledelayedexpansion
echo ==========================================
echo    FloodSentry - Setup ^& Requirements Check
echo ==========================================

:: 1. Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] Python is not installed or not added to PATH.
    
    winget --version >nul 2>&1
    if %errorlevel% equ 0 (
        set /p install_py="Would you like to install Python 3.11 via winget now? (y/n): "
        if /i "!install_py!"=="y" (
            echo Installing Python...
            winget install Python.Python.3.11 --silent --show-progress
            echo.
            echo [!] Python installed. PLEASE RESTART THIS TERMINAL for changes to take effect, then run setup again.
            pause
            exit /b
        )
    ) else (
        echo [ERROR] Python is missing and winget is not available.
        echo Please install Python manually from https://www.python.org/downloads/
        pause
        exit /b
    )
)
echo [OK] Python is installed.

:: 2. Setup Backend (Python)
echo.
echo --- Setting up Backend ---
cd backend

if not exist venv\ (
    echo Creating virtual environment...
    python -m venv venv
)

echo Activating virtual environment and checking/installing dependencies...
call venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt

:: Check if the database needs seeding
if not exist floodsentry.db (
    echo Seeding the database with initial data...
    python scripts/seed_db.py
)

cd ..

:: 3. Check Node.js / NPM
npm --version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [!] Node.js ^(npm^) is missing.
    
    winget --version >nul 2>&1
    if %errorlevel% equ 0 (
        set /p install_node="Would you like to install Node.js (LTS) via winget now? (y/n): "
        if /i "!install_node!"=="y" (
            echo Installing Node.js...
            winget install OpenJS.NodeJS.LTS --silent --show-progress
            echo.
            echo [!] Node.js installed. PLEASE RESTART THIS TERMINAL for changes to take effect, then run setup again.
            pause
            exit /b
        )
    ) else (
        echo [ERROR] Node.js is missing and winget is not available.
        echo Please install Node.js manually from https://nodejs.org/
        pause
        exit /b
    )
) else (
    echo [OK] Node.js ^(npm^) is installed.
)

echo.
echo --- Setting up Frontend ---
cd frontend
echo Checking/installing frontend dependencies...
call npm install
cd ..

echo.
echo ==========================================
echo    Setup Complete!
echo    You can now run 'run_project.bat'
echo ==========================================
pause
