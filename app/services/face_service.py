"""
Face Recognition Service (ONNX Runtime — no insightface package needed)

Uses:
- OpenCV Haar cascade for face detection (built-in, zero downloads)
- w600k_r50.onnx (ArcFace) for face embeddings via onnxruntime
- Optional: det_10g.onnx (SCRFD) for better detection if available

Models go in /models/ folder. Run download_model.py first.
"""
import numpy as np
import cv2
import os
import logging
from typing import Optional, Tuple, Dict
from datetime import datetime
from pathlib import Path
from sqlalchemy.orm import Session

from app.config import settings
from app.models.staff import Staff, FaceEmbedding

logger = logging.getLogger(__name__)

# ── Paths ────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent.parent
MODEL_DIR = BASE_DIR / "models"
RECOGNITION_MODEL = MODEL_DIR / "w600k_r50.onnx"
DETECTION_MODEL = MODEL_DIR / "det_10g.onnx"

# ── Global Cache ─────────────────────────────────────
_rec_session = None        # onnxruntime recognition session
_det_session = None        # onnxruntime detection session (optional)
_face_cascade = None       # OpenCV Haar cascade (fallback detector)
_embedding_cache: Dict[int, np.ndarray] = {}


# ═══════════════════════════════════════════════════════
# MODEL LOADING
# ═══════════════════════════════════════════════════════

def get_recognition_session():
    """Load ArcFace w600k_r50.onnx recognition model."""
    global _rec_session
    if _rec_session is None:
        import onnxruntime as ort
        if not RECOGNITION_MODEL.exists():
            raise RuntimeError(
                f"Recognition model not found at {RECOGNITION_MODEL}\n"
                f"Run: python download_model.py"
            )
        _rec_session = ort.InferenceSession(
            str(RECOGNITION_MODEL),
            providers=["CPUExecutionProvider"]
        )
        logger.info(f"Loaded recognition model: {RECOGNITION_MODEL.name}")
    return _rec_session


def get_face_detector():
    """Get face detector — tries SCRFD first, falls back to Haar cascade."""
    global _det_session, _face_cascade

    # Option 1: SCRFD det_10g.onnx (better accuracy)
    if _det_session is not None:
        return "scrfd", _det_session

    if DETECTION_MODEL.exists() and _det_session is None:
        try:
            import onnxruntime as ort
            _det_session = ort.InferenceSession(
                str(DETECTION_MODEL),
                providers=["CPUExecutionProvider"]
            )
            logger.info(f"Using SCRFD detector: {DETECTION_MODEL.name}")
            return "scrfd", _det_session
        except Exception as e:
            logger.warning(f"Failed to load SCRFD: {e}, falling back to Haar")

    # Option 2: OpenCV Haar cascade (always available, no download)
    if _face_cascade is None:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _face_cascade = cv2.CascadeClassifier(cascade_path)
        logger.info("Using OpenCV Haar cascade face detector")
    return "haar", _face_cascade


# ═══════════════════════════════════════════════════════
# FACE DETECTION
# ═══════════════════════════════════════════════════════

def detect_faces_haar(image: np.ndarray, cascade) -> list:
    """Detect faces using OpenCV Haar cascade. Returns list of (x,y,w,h)."""
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    gray = cv2.equalizeHist(gray)
    faces = cascade.detectMultiScale(
        gray,
        scaleFactor=1.1,
        minNeighbors=5,
        minSize=(settings.MIN_FACE_SIZE, settings.MIN_FACE_SIZE),
        flags=cv2.CASCADE_SCALE_IMAGE
    )
    if len(faces) == 0:
        return []
    return [(int(x), int(y), int(w), int(h)) for (x, y, w, h) in faces]


def detect_faces_scrfd(image: np.ndarray, session) -> list:
    """
    Detect faces using SCRFD det_10g.onnx.
    Returns list of (x, y, w, h, confidence).
    """
    img_h, img_w = image.shape[:2]

    # Prepare input: resize to 640x640
    det_size = 640
    scale = min(det_size / img_h, det_size / img_w)
    new_w, new_h = int(img_w * scale), int(img_h * scale)
    resized = cv2.resize(image, (new_w, new_h))

    # Pad to 640x640
    padded = np.full((det_size, det_size, 3), 127, dtype=np.uint8)
    padded[:new_h, :new_w, :] = resized

    # Normalize: (img - 127.5) / 128.0
    blob = (padded.astype(np.float32) - 127.5) / 128.0
    blob = blob.transpose(2, 0, 1)[np.newaxis, ...]  # 1x3x640x640

    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: blob})

    faces = []
    num_outputs = len(outputs)

    if num_outputs >= 9:
        # Full SCRFD with keypoints
        strides = [8, 16, 32]
        for idx, stride in enumerate(strides):
            scores = outputs[idx * 3]
            bboxes = outputs[idx * 3 + 1]

            feat_h = det_size // stride
            feat_w = det_size // stride
            anchors_y, anchors_x = np.mgrid[:feat_h, :feat_w]
            anchors = np.stack([anchors_x.ravel(), anchors_y.ravel()], axis=1).astype(np.float32)
            anchors = (anchors * stride).astype(np.float32)

            score_thresh = 0.5
            for i in range(len(scores[0])):
                score = float(scores[0][i][0]) if scores[0][i].ndim > 0 else float(scores[0][i])
                if score < score_thresh:
                    continue

                cx, cy = anchors[i]
                bbox = bboxes[0][i]
                x1 = (cx - bbox[0] * stride) / scale
                y1 = (cy - bbox[1] * stride) / scale
                x2 = (cx + bbox[2] * stride) / scale
                y2 = (cy + bbox[3] * stride) / scale

                x1 = max(0, int(x1))
                y1 = max(0, int(y1))
                x2 = min(img_w, int(x2))
                y2 = min(img_h, int(y2))

                w = x2 - x1
                h = y2 - y1
                if w > settings.MIN_FACE_SIZE and h > settings.MIN_FACE_SIZE:
                    faces.append((x1, y1, w, h, score))

        if faces:
            faces = nms(faces, 0.4)
    else:
        logger.warning(f"Unexpected SCRFD output count: {num_outputs}, falling back to Haar")
        det_type, detector = "haar", get_face_detector()[1]
        if det_type == "haar":
            return [(x, y, w, h, 0.99) for x, y, w, h in detect_faces_haar(image, detector)]

    return faces


def nms(faces, iou_thresh):
    """Simple Non-Maximum Suppression."""
    if not faces:
        return []
    faces = sorted(faces, key=lambda f: f[4], reverse=True)
    keep = []
    for face in faces:
        x1, y1, w1, h1, s1 = face
        discard = False
        for kept in keep:
            x2, y2, w2, h2, s2 = kept
            ix1 = max(x1, x2)
            iy1 = max(y1, y2)
            ix2 = min(x1 + w1, x2 + w2)
            iy2 = min(y1 + h1, y2 + h2)
            inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
            area1 = w1 * h1
            area2 = w2 * h2
            iou = inter / (area1 + area2 - inter + 1e-6)
            if iou > iou_thresh:
                discard = True
                break
        if not discard:
            keep.append(face)
    return keep


def detect_faces(image: np.ndarray) -> list:
    """
    Detect faces using best available detector.
    Returns: list of (x, y, w, h) or (x, y, w, h, confidence)
    """
    global _face_cascade
    det_type, detector = get_face_detector()

    if det_type == "scrfd":
        try:
            faces = detect_faces_scrfd(image, detector)
            if faces:
                return faces
        except Exception as e:
            logger.warning(f"SCRFD detection failed: {e}, falling back to Haar")

        if _face_cascade is None:
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            _face_cascade = cv2.CascadeClassifier(cascade_path)
            logger.info("Loaded Haar cascade as fallback detector")

        raw = detect_faces_haar(image, _face_cascade)
        return [(x, y, w, h, 0.99) for x, y, w, h in raw]
    else:
        raw = detect_faces_haar(image, detector)
        return [(x, y, w, h, 0.99) for x, y, w, h in raw]


# ═══════════════════════════════════════════════════════
# FACE ALIGNMENT + EMBEDDING
# ═══════════════════════════════════════════════════════

def align_face(image: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
    """
    Crop and align face to 112x112 for ArcFace input.
    Adds margin around detected bbox for better recognition.
    """
    img_h, img_w = image.shape[:2]

    margin_x = int(w * 0.3)
    margin_y = int(h * 0.3)

    x1 = max(0, x - margin_x)
    y1 = max(0, y - margin_y)
    x2 = min(img_w, x + w + margin_x)
    y2 = min(img_h, y + h + margin_y)

    face_crop = image[y1:y2, x1:x2]
    face_aligned = cv2.resize(face_crop, (112, 112))
    return face_aligned


def get_embedding(face_112: np.ndarray) -> np.ndarray:
    """
    Extract 512-dim embedding from aligned 112x112 face.
    Input: BGR 112x112 uint8 image
    Output: normalized 512-dim float32 embedding
    """
    session = get_recognition_session()

    face_rgb = cv2.cvtColor(face_112, cv2.COLOR_BGR2RGB)
    face_float = face_rgb.astype(np.float32)
    face_norm = (face_float - 127.5) / 127.5
    blob = face_norm.transpose(2, 0, 1)[np.newaxis, ...]

    input_name = session.get_inputs()[0].name
    outputs = session.run(None, {input_name: blob})
    embedding = outputs[0][0]  # shape: (512,)

    norm = np.linalg.norm(embedding)
    if norm > 0:
        embedding = embedding / norm

    return embedding.astype(np.float32)


def extract_embedding(image: np.ndarray) -> Tuple[Optional[np.ndarray], float, str]:
    """
    Full pipeline: detect → align → embed.
    Returns: (embedding, confidence, error_message)
    """
    faces = detect_faces(image)

    if len(faces) == 0:
        return None, 0.0, "No face detected in the image"

    if len(faces) > 1:
        return None, 0.0, f"Multiple faces detected ({len(faces)}). Only one face allowed."

    face = faces[0]
    x, y, w, h = int(face[0]), int(face[1]), int(face[2]), int(face[3])
    det_conf = float(face[4]) if len(face) > 4 else 0.99

    if w < settings.MIN_FACE_SIZE or h < settings.MIN_FACE_SIZE:
        return None, 0.0, f"Face too small ({w}x{h}px). Move closer to camera."

    face_aligned = align_face(image, x, y, w, h)
    embedding = get_embedding(face_aligned)

    return embedding, det_conf, ""


# ═══════════════════════════════════════════════════════
# IMAGE DECODE + LIVENESS + ANTI-SPOOF
# ═══════════════════════════════════════════════════════

def decode_image(image_bytes: bytes) -> np.ndarray:
    """Decode image bytes to OpenCV BGR array."""
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image data")
    return img


def basic_liveness_check(image: np.ndarray) -> Tuple[bool, str]:
    """
    Basic anti-spoofing checks:
    1. Sharpness (Laplacian) — screens/photos are blurrier
    2. Glare detection — screen reflections
    3. Texture variance — printed photos
    """
    if not settings.LIVENESS_ENABLED:
        return True, ""

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Sharpness check
    laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
    if laplacian_var < 30:
        return False, f"Image appears to be from a screen/photo (blur score: {laplacian_var:.1f})"

    # Glare check
    hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
    _, _, v_channel = cv2.split(hsv)
    bright_pixels = np.sum(v_channel > 250) / v_channel.size
    if bright_pixels > 0.25:
        return False, "Excessive glare detected - possible screen replay"

    # Texture check
    texture_score = gray.std()
    if texture_score < 15:
        return False, "Low texture variance - possible printed photo"

    return True, ""


def check_antispoof(
    image: np.ndarray,
    face_bbox: Tuple[int, int, int, int],
    threshold: float = 0.5
) -> Tuple[bool, float, str]:
    """
    Anti-spoofing check. Delegates to basic_liveness_check.
    Returns: (is_real, confidence, reason)
    """
    is_live, msg = basic_liveness_check(image)
    confidence = 1.0 if is_live else 0.0
    return is_live, confidence, msg


# ═══════════════════════════════════════════════════════
# MATCHING + CACHE
# ═══════════════════════════════════════════════════════

def embedding_to_bytes(embedding: np.ndarray) -> bytes:
    return embedding.astype(np.float32).tobytes()


def bytes_to_embedding(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype=np.float32).copy()


def compute_similarity(emb1: np.ndarray, emb2: np.ndarray) -> float:
    """Cosine similarity between two L2-normalized embeddings."""
    return float(np.dot(emb1, emb2))


def load_embedding_cache(db: Session):
    """Load all active face embeddings into memory."""
    global _embedding_cache
    _embedding_cache.clear()

    active_embeddings = db.query(FaceEmbedding).filter(
        FaceEmbedding.is_active == True
    ).all()

    for fe in active_embeddings:
        _embedding_cache[fe.staff_id] = bytes_to_embedding(fe.embedding)

    logger.info(f"Loaded {len(_embedding_cache)} face embeddings into cache")


def match_face(
    embedding: np.ndarray,
    db: Session,
    threshold: Optional[float] = None
) -> Tuple[Optional[int], float]:
    """Match face against all registered staff."""
    if threshold is None:
        threshold = settings.FACE_MATCH_THRESHOLD

    if not _embedding_cache:
        load_embedding_cache(db)

    best_match_id = None
    best_score = 0.0

    for staff_id, stored_emb in _embedding_cache.items():
        score = compute_similarity(embedding, stored_emb)
        if score > best_score:
            best_score = score
            best_match_id = staff_id

    if best_score >= threshold:
        return best_match_id, best_score
    return None, best_score


# ═══════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════

def register_face(
    staff_id: int,
    image_bytes: bytes,
    db: Session,
    registered_by: str = "system"
) -> Tuple[bool, str]:
    """Register face for a staff member. Archives old embeddings."""
    try:
        image = decode_image(image_bytes)
    except ValueError as e:
        return False, str(e)

    # Liveness check
    is_live, msg = basic_liveness_check(image)
    if not is_live:
        return False, f"Liveness check failed: {msg}"

    # Anti-spoof check during registration
    faces = detect_faces(image)
    if faces:
        x, y, w, h = int(faces[0][0]), int(faces[0][1]), int(faces[0][2]), int(faces[0][3])
        is_real, _, spoof_reason = check_antispoof(image, (x, y, w, h))
        if not is_real:
            return False, f"Anti-spoofing failed during registration: {spoof_reason}"

    # Extract embedding
    embedding, confidence, error = extract_embedding(image)
    if embedding is None:
        return False, error

    # Archive existing embeddings
    existing = db.query(FaceEmbedding).filter(
        FaceEmbedding.staff_id == staff_id,
        FaceEmbedding.is_active == True
    ).all()

    max_version = 0
    for fe in existing:
        fe.is_active = False
        fe.archived_at = datetime.utcnow()
        max_version = max(max_version, fe.version)

    # Store new
    new_emb = FaceEmbedding(
        staff_id=staff_id,
        embedding=embedding_to_bytes(embedding),
        version=max_version + 1,
        is_active=True,
        registered_by=registered_by,
    )
    db.add(new_emb)
    db.commit()

    # Update cache
    _embedding_cache[staff_id] = embedding

    return True, f"Face registered (v{max_version + 1}, confidence: {confidence:.2f})"


def register_face_multi(
    staff_id: int,
    image_bytes_list: list,
    db: Session,
    registered_by: str = "system",
) -> Tuple[bool, str]:
    """
    Register face by averaging embeddings across multiple photos.
    - Each image is liveness-checked and embedding-extracted independently.
    - Any image that fails liveness or detection is skipped (logged as warning).
    - Requires at least 1 successful embedding.
    - Averaged embedding is L2-normalized before storage.
    """
    valid_embeddings = []
    skipped = 0

    for i, image_bytes in enumerate(image_bytes_list):
        try:
            image = decode_image(image_bytes)
        except ValueError as e:
            logger.warning(f"Photo {i+1}: decode failed — {e}")
            skipped += 1
            continue

        is_live, msg = basic_liveness_check(image)
        if not is_live:
            logger.warning(f"Photo {i+1}: liveness failed — {msg}")
            skipped += 1
            continue

        embedding, confidence, error = extract_embedding(image)
        if embedding is None:
            logger.warning(f"Photo {i+1}: embedding failed — {error}")
            skipped += 1
            continue

        valid_embeddings.append(embedding)
        logger.debug(f"Photo {i+1}: OK (conf={confidence:.3f})")

    if not valid_embeddings:
        return False, (
            f"All {len(image_bytes_list)} photos failed "
            f"(liveness / face-not-detected). Please retake."
        )

    if skipped:
        logger.warning(f"Face registration: {skipped}/{len(image_bytes_list)} photos skipped")

    # Average and re-normalize
    averaged = np.mean(valid_embeddings, axis=0).astype(np.float32)
    norm = np.linalg.norm(averaged)
    if norm > 0:
        averaged = averaged / norm

    logger.info(f"Averaging {len(valid_embeddings)} embeddings for staff {staff_id}")

    # Archive existing embeddings
    existing = db.query(FaceEmbedding).filter(
        FaceEmbedding.staff_id == staff_id,
        FaceEmbedding.is_active == True,
    ).all()

    max_version = 0
    for fe in existing:
        fe.is_active = False
        fe.archived_at = datetime.utcnow()
        max_version = max(max_version, fe.version)

    new_emb = FaceEmbedding(
        staff_id=staff_id,
        embedding=embedding_to_bytes(averaged),
        version=max_version + 1,
        is_active=True,
        registered_by=registered_by,
    )
    db.add(new_emb)
    db.commit()

    _embedding_cache[staff_id] = averaged

    return True, (
        f"Face registered from {len(valid_embeddings)} photos "
        f"(v{max_version + 1}, averaged embedding)"
    )


def process_punch_image(
    image_bytes: bytes,
    db: Session
) -> Tuple[Optional[int], float, str]:
    """
    Full pipeline: decode → liveness → antispoof → detect → embed → match.
    Returns: (staff_id, confidence, error_message)
    """
    try:
        image = decode_image(image_bytes)
    except ValueError as e:
        return None, 0.0, str(e)

    # Liveness check
    is_live, msg = basic_liveness_check(image)
    if not is_live:
        return None, 0.0, f"Liveness failed: {msg}"

    # Anti-spoof check (detect face first to get bbox)
    faces = detect_faces(image)
    if faces:
        x, y, w, h = int(faces[0][0]), int(faces[0][1]), int(faces[0][2]), int(faces[0][3])
        is_real, real_conf, spoof_reason = check_antispoof(
            image, (x, y, w, h),
            threshold=settings.ANTISPOOF_THRESHOLD
        )
        if not is_real:
            return None, 0.0, f"Anti-spoofing failed: {spoof_reason}"

    # Extract embedding
    embedding, det_conf, error = extract_embedding(image)
    if embedding is None:
        return None, det_conf, error

    # Match
    staff_id, match_conf = match_face(embedding, db)
    if staff_id is None:
        return None, match_conf, (
            f"No matching face found "
            f"(best score: {match_conf:.3f}, threshold: {settings.FACE_MATCH_THRESHOLD})"
        )

    return staff_id, match_conf, ""