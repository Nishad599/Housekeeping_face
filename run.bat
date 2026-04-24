@echo off
title Face Attendance System
echo ========================================
echo   Face Attendance System
echo   Shift: 7:00 AM - 4:00 PM
echo   OT: After 4:00 PM
echo ========================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.9+ from python.org
    echo Make sure "Add Python to PATH" is checked during install.
    pause
    exit /b 1
)

:: Create virtual environment if not exists
if not exist "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

:: Activate venv
call venv\Scripts\activate.bat

:: Upgrade pip
python -m pip install --upgrade pip --quiet

:: Install dependencies
echo.
echo Installing dependencies...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo.
    echo Retrying with relaxed versions...
    pip install fastapi uvicorn[standard] sqlalchemy python-dotenv python-jose[cryptography] passlib[bcrypt] python-multipart jinja2 numpy openpyxl aiofiles opencv-python onnxruntime
)

:: Create upload directory
if not exist "static\uploads\faces" mkdir static\uploads\faces

:: Download models if not present
if not exist "models\w600k_r50.onnx" (
    echo.
    echo Downloading face recognition models...
    python download_model.py
    if errorlevel 1 (
        echo.
        echo MODEL DOWNLOAD FAILED - see instructions above.
        echo You can also download manually from:
        echo   https://huggingface.co/yolkailtd/face-swap-models/tree/main/insightface/models/buffalo_l
        echo Place w600k_r50.onnx and det_10g.onnx in the models folder.
        pause
    )
)

:: Start server
echo.
echo =============================================
echo   Server running at http://localhost:8000
echo.
echo   Punch Kiosk : http://localhost:8000/punch
echo   Admin Login : http://localhost:8000/login
echo   Dashboard   : http://localhost:8000/dashboard
echo   API Docs    : http://localhost:8000/docs
echo.
echo   Default login: admin / admin123
echo   Press Ctrl+C to stop
echo =============================================
echo.

python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
pause
