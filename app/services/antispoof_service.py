"""
ML-based Face Anti-Spoofing using MiniFASNetV2 (ONNX, CPU-only).
Model: 2.7_80x80_MiniFASNetV2.onnx  (~1MB, <50ms on CPU)
Place at: /models/anti_spoof_mn3.onnx
"""
import numpy as np
import cv2
import logging
from pathlib import Path
from typing import Tuple, Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent.parent
MODEL_DIR = BASE_DIR / "models"
ANTISPOOF_MODEL = MODEL_DIR / "anti_spoof_mn3.onnx"

_session = None


def _get_session():
    global _session
    if _session is None:
        import onnxruntime as ort
        if not ANTISPOOF_MODEL.exists():
            raise RuntimeError(
                f"Anti-spoof model missing at {ANTISPOOF_MODEL}\n"
                f"Run: python download_models.py  OR  wget the model manually."
            )
        _session = ort.InferenceSession(
            str(ANTISPOOF_MODEL),
            providers=["CPUExecutionProvider"]
        )
        logger.info("Loaded MiniFASNet anti-spoof model (CPU)")
    return _session


def _preprocess(face_bgr: np.ndarray) -> np.ndarray:
    """Resize to 80x80, normalize to [-1, 1], return NCHW float32."""
    resized = cv2.resize(face_bgr, (80, 80))
    rgb     = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
    blob    = (rgb.astype(np.float32) - 127.5) / 127.5
    return blob.transpose(2, 0, 1)[np.newaxis, ...]   # 1x3x80x80


def check_antispoof(
    full_image: np.ndarray,
    bbox: Tuple[int, int, int, int],
    threshold: float = 0.7,
) -> Tuple[bool, float, str]:
    """
    Args:
        full_image : full BGR frame (numpy array)
        bbox       : (x, y, w, h) face bounding box from detect_faces()
        threshold  : minimum 'real' probability to pass (0.0–1.0)

    Returns:
        (is_real, real_confidence, rejection_reason)
    """
    # Crop face with small margin for context
    x, y, w, h = bbox
    img_h, img_w = full_image.shape[:2]
    mx = int(w * 0.15)
    my = int(h * 0.15)
    face_crop = full_image[
        max(0, y - my) : min(img_h, y + h + my),
        max(0, x - mx) : min(img_w, x + w + mx),
    ]

    try:
        session    = _get_session()
        blob       = _preprocess(face_crop)
        input_name = session.get_inputs()[0].name
        probs      = session.run(None, {input_name: blob})[0][0]
        # probs[0] = spoof,  probs[1] = real
        real_prob  = float(probs[1])
        spoof_prob = float(probs[0])
    except RuntimeError as e:
        # Model file missing — fail open so punches still work without model
        logger.warning(f"Anti-spoof skipped (model unavailable): {e}")
        return True, 1.0, ""
    except Exception as e:
        logger.error(f"Anti-spoof inference error: {e}")
        return True, 1.0, ""   # fail open on unexpected errors

    logger.debug(f"Anti-spoof → real={real_prob:.3f}  spoof={spoof_prob:.3f}")

    if real_prob >= threshold:
        return True, real_prob, ""

    if spoof_prob > 0.8:
        reason = f"Spoofing detected — printed photo or screen replay ({spoof_prob:.0%} confidence)"
    else:
        reason = f"Anti-spoof check failed (real score: {real_prob:.0%}, required: {threshold:.0%})"

    return False, real_prob, reason