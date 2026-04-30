"""
Download Buffalo_L face recognition model from HuggingFace.
Run this once before starting the server.

Usage:
    python download_model.py
"""
import os
import sys
import urllib.request

MODEL_DIR = os.path.join(os.path.dirname(__file__), "models")
MODEL_URL = "https://huggingface.co/yolkailtd/face-swap-models/resolve/main/insightface/models/buffalo_l/w600k_r50.onnx"
MODEL_FILE = os.path.join(MODEL_DIR, "w600k_r50.onnx")

# SCRFD face detection model (small, fast)
DET_URL = "https://huggingface.co/yolkailtd/face-swap-models/resolve/main/insightface/models/buffalo_l/det_10g.onnx"
DET_FILE = os.path.join(MODEL_DIR, "det_10g.onnx")

# MiniFASNetV2 anti-spoofing model (~1 MB)
ANTISPOOF_URL = "https://github.com/yakhyo/face-anti-spoofing/releases/download/weights/MiniFASNetV2.onnx"
ANTISPOOF_FILE = os.path.join(MODEL_DIR, "MiniFASNetV2.onnx")


def download_file(url, dest, label):
    """Download with progress bar."""
    if os.path.exists(dest):
        size_mb = os.path.getsize(dest) / (1024 * 1024)
        print(f"  [OK] {label} already exists ({size_mb:.1f} MB)")
        return True

    print(f"  Downloading {label}...")
    print(f"  From: {url}")

    try:
        def progress(block_num, block_size, total_size):
            downloaded = block_num * block_size
            if total_size > 0:
                pct = min(100, downloaded * 100 / total_size)
                mb = downloaded / (1024 * 1024)
                total_mb = total_size / (1024 * 1024)
                sys.stdout.write(f"\r  [{pct:5.1f}%] {mb:.1f} / {total_mb:.1f} MB")
                sys.stdout.flush()

        urllib.request.urlretrieve(url, dest, reporthook=progress)
        print(f"\n  [OK] {label} downloaded successfully")
        return True
    except Exception as e:
        print(f"\n  [ERROR] Failed to download {label}: {e}")
        print(f"  Please download manually from:")
        print(f"    {url}")
        print(f"  And place it in: {dest}")
        return False


def main():
    print("=" * 55)
    print("  Face Attendance - Model Setup")
    print("=" * 55)
    print()

    os.makedirs(MODEL_DIR, exist_ok=True)

    print("[1/3] Face Recognition Model (w600k_r50.onnx ~174 MB)")
    ok1 = download_file(MODEL_URL, MODEL_FILE, "w600k_r50.onnx")

    print()
    print("[2/3] Face Detection Model (det_10g.onnx ~16 MB)")
    ok2 = download_file(DET_URL, DET_FILE, "det_10g.onnx")

    print()
    print("[3/3] Anti-Spoofing Model (MiniFASNetV2.onnx ~1 MB)")
    ok3 = download_file(ANTISPOOF_URL, ANTISPOOF_FILE, "MiniFASNetV2.onnx")

    print()
    if ok1 and ok2 and ok3:
        print("=" * 55)
        print("  All models ready! You can now run:")
        print("  python -m uvicorn app.main:app --port 8000 --reload")
        print("=" * 55)
    else:
        print("Some models failed to download. See errors above.")
        print("You can download them manually.")

    return 0 if (ok1 and ok2 and ok3) else 1


if __name__ == "__main__":
    sys.exit(main())
