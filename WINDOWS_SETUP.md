# Windows Setup Guide

## Prerequisites

**Python 3.9+** — Download from [python.org](https://www.python.org/downloads/)
- CHECK "Add Python to PATH" during installation
- CHECK "Install pip"

That's it. No Visual Studio Build Tools needed.

---

## Quick Start (2 steps)

### Step 1: Delete old venv (if you had one from the insightface attempt)
```cmd
rmdir /s /q venv
```

### Step 2: Double-click `run.bat`

It will:
1. Create a fresh virtual environment
2. Install all dependencies (no insightface — pure pip wheels)
3. Download face recognition models (~190 MB one-time)
4. Start the server

---

## Manual Setup

```cmd
:: Delete old venv if exists
rmdir /s /q venv

:: Create fresh venv
python -m venv venv
venv\Scripts\activate

:: Install (all pure wheels, no C++ build needed)
pip install -r requirements.txt

:: Download models (one-time, ~190 MB)
python download_model.py

:: Run
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## What Changed (vs insightface version)

| Before | Now |
|--------|-----|
| `insightface` package (needs C++ compiler) | Direct ONNX Runtime (pure pip install) |
| `opencv-python-headless` | `opencv-python` (Windows camera support) |
| Model downloaded by insightface internally | `download_model.py` fetches from HuggingFace |

**Same models, same accuracy** — we just load them directly via onnxruntime instead of through the insightface wrapper.

---

## After Starting

| Page | URL |
|------|-----|
| **Punch Kiosk** | http://localhost:8000/punch |
| **Admin Login** | http://localhost:8000/login |
| **Dashboard** | http://localhost:8000/dashboard |
| **Staff Management** | http://localhost:8000/staff |
| **Muster Book** | http://localhost:8000/muster |
| **API Docs** | http://localhost:8000/docs |

**Default login:** `admin` / `admin123`

---

## First Use

1. **Login** → http://localhost:8000/login → admin / admin123
2. **Add Staff** → Staff page → "+ Add Staff" → Fill employee ID, name, etc.
3. **Register Face** → Click "📷 Face" button → Allow camera → Capture
4. **Punch** → http://localhost:8000/punch → Look at camera → Click PUNCH
5. **View Reports** → Dashboard (today) or Muster Book (monthly)

---

## If Model Download Fails

Download these 2 files manually from HuggingFace:

1. **w600k_r50.onnx** (~174 MB) — Face recognition
   https://huggingface.co/yolkailtd/face-swap-models/resolve/main/insightface/models/buffalo_l/w600k_r50.onnx

2. **det_10g.onnx** (~16 MB) — Face detection
   https://huggingface.co/yolkailtd/face-swap-models/resolve/main/insightface/models/buffalo_l/det_10g.onnx

Place both files in the `models/` folder inside the project.

---

## Troubleshooting

### "Camera not working"
- Use Chrome or Edge
- Allow camera permission when prompted
- Close other apps using the camera (Zoom, Teams, etc.)

### Port 8000 already in use
```cmd
uvicorn app.main:app --port 8080 --reload
```

### numpy version conflict
```cmd
pip install numpy==1.26.2 --force-reinstall
```
