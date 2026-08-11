"""
Dual-engine OCR module – PaddleOCR + Tesseract with adaptive fallback.

Strategy
--------
1. Run PaddleOCR.
2. If PaddleOCR's mean confidence is below OCR_CONFIDENCE_THRESHOLD, also run
   Tesseract on the same image and compute *its* confidence from its word-level
   data.
3. Keep whichever result has the higher mean confidence.
4. Return full_text, elements, overall_confidence, and the name of the engine
   that won ("paddle", "tesseract", or "paddle_only" when Tesseract is absent).

This keeps the public API identical to the original – callers that only unpack
the first three return values continue to work unchanged.
"""

import os
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.environ["FLAGS_enable_pir_api"] = "0"
os.environ["FLAGS_use_mkldnn"] = "0"

import tempfile
import numpy as np
from PIL import Image
from paddleocr import PaddleOCR
import config as _cfg

# ── Tesseract setup ──────────────────────────────────────────────────────────
# pytesseract is a thin wrapper; the actual binary must also be installed.
# Common Windows locations are tried automatically.
_TESSERACT_AVAILABLE = False
try:
    import pytesseract
    from pytesseract import Output

    _TESSERACT_CANDIDATE_PATHS = [
        r"C:\Program Files\Tesseract-OCR\tesseract.exe",
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        r"C:\Users\shailesh\Desktop\Ujjval\08-Softwares\Tesseract-OCR\tesseract.exe",
        r"C:\Users\shailesh\AppData\Local\Programs\Tesseract-OCR\tesseract.exe",
    ]
    # Honour explicit path from config / env first
    if _cfg.TESSERACT_PATH and os.path.isfile(_cfg.TESSERACT_PATH):
        pytesseract.pytesseract.tesseract_cmd = _cfg.TESSERACT_PATH
    elif not pytesseract.pytesseract.tesseract_cmd or not os.path.isfile(
        pytesseract.pytesseract.tesseract_cmd
    ):
        for _p in _TESSERACT_CANDIDATE_PATHS:
            if os.path.isfile(_p):
                pytesseract.pytesseract.tesseract_cmd = _p
                break

    # Quick smoke-test
    pytesseract.get_tesseract_version()
    _TESSERACT_AVAILABLE = True
    print(f"[OCR] Tesseract available: {pytesseract.pytesseract.tesseract_cmd}")
except Exception as _tess_err:
    print(f"[OCR] Tesseract not available ({_tess_err}). Paddle-only mode active.")

# ── PaddleOCR initialisation ─────────────────────────────────────────────────
print("[OCR] Initialising PaddleOCR …")
ocr_engine = PaddleOCR(
    lang="en",
    ocr_version="PP-OCRv4",
    device="cpu",
    enable_mkldnn=False,
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
)
print("[OCR] PaddleOCR ready.")

# ── Confidence threshold that triggers fallback ──────────────────────────────
# Read from config so it can be tuned in one place.
OCR_CONFIDENCE_THRESHOLD = getattr(_cfg, "OCR_CONFIDENCE_THRESHOLD", 0.80)


# ── Internal helpers ─────────────────────────────────────────────────────────

def _result_value(result, name, default=None):
    """Read a PaddleOCR result field from either an object or a mapping."""
    value = getattr(result, name, None)
    if value is None and isinstance(result, dict):
        value = result.get(name)
    if value is None and hasattr(result, "to_dict"):
        value = result.to_dict().get(name)
    return default if value is None else value


def _as_list(value):
    """Convert PaddleOCR/NumPy containers without truth-value checks."""
    if value is None:
        return []
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, (list, tuple)):
        return [item.tolist() if isinstance(item, np.ndarray) else item for item in value]
    return [value]


def _mean_conf(elements: list) -> float:
    if not elements:
        return 0.0
    return sum(e["confidence"] for e in elements) / len(elements)


# ── PaddleOCR extraction ─────────────────────────────────────────────────────

def _run_paddle(tmp_path: str) -> tuple:
    """
    Run PaddleOCR on a saved PNG file.
    Returns (full_text, elements, overall_confidence).
    """
    elements = []
    full_text_lines = []

    try:
        results = ocr_engine.predict(tmp_path)

        for result in results:
            texts  = _as_list(_result_value(result, "rec_texts"))
            scores = _as_list(_result_value(result, "rec_scores"))
            boxes  = _as_list(_result_value(result, "dt_polys"))
            if not boxes:
                boxes = _as_list(_result_value(result, "dt_boxes"))

            scores.extend([1.0] * (len(texts) - len(scores)))
            boxes.extend([[]]  * (len(texts) - len(boxes)))

            for text, conf, box in zip(texts, scores, boxes):
                if text and text.strip():
                    elements.append({
                        "text":       text,
                        "confidence": float(conf),
                        "box":        box,
                    })
                    full_text_lines.append(text)

    except Exception as e:
        print(f"[OCR][Paddle] Error: {e}")

    full_text = "\n".join(full_text_lines)
    return full_text, elements, _mean_conf(elements)


# ── Tesseract extraction ─────────────────────────────────────────────────────

def _run_tesseract(pil_image: Image.Image) -> tuple:
    """
    Run Tesseract on a PIL image.
    Word-level confidence is obtained from image_to_data(); non-text rows
    (conf == -1) are ignored.
    Returns (full_text, elements, overall_confidence).
    """
    elements = []
    full_text_lines = []

    try:
        # Get word-level data including bounding boxes and confidence
        df = pytesseract.image_to_data(
            pil_image,
            lang="eng",
            config="--psm 3",   # fully automatic page segmentation
            output_type=Output.DICT,
        )

        n = len(df["text"])
        for i in range(n):
            conf_raw = int(df["conf"][i])
            word     = df["text"][i]
            if conf_raw < 0 or not word or not word.strip():
                continue  # -1 means no data; skip blanks

            conf_norm = conf_raw / 100.0           # tesseract gives 0-100
            x, y, w, h = df["left"][i], df["top"][i], df["width"][i], df["height"][i]
            box = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]

            elements.append({
                "text":       word.strip(),
                "confidence": conf_norm,
                "box":        box,
            })
            full_text_lines.append(word.strip())

        # Re-assemble full text preserving line breaks via Tesseract's own output
        full_text_plain = pytesseract.image_to_string(
            pil_image, lang="eng", config="--psm 3"
        ).strip()
        full_text = full_text_plain if full_text_plain else " ".join(full_text_lines)

    except Exception as e:
        print(f"[OCR][Tesseract] Error: {e}")

    return full_text, elements, _mean_conf(elements)


# ── Public API ───────────────────────────────────────────────────────────────

def perform_ocr(pil_image: Image.Image):
    """
    Run OCR on a PIL Image using an adaptive dual-engine strategy.

    Flow:
      1. PaddleOCR runs first (file-path mode to avoid oneDNN crash).
      2. If confidence >= OCR_CONFIDENCE_THRESHOLD  →  done, return Paddle result.
      3. Otherwise also run Tesseract and compare mean confidences.
      4. The result with the higher mean confidence is returned.

    Returns:
      full_text         (str)
      elements          (list of dicts: {text, confidence, box})
      overall_confidence (float, 0-1)
      engine_used       (str: "paddle", "tesseract", or "paddle_only")
    """
    tmp_path = None
    engine_used = "paddle_only"

    try:
        # Save to temp PNG so Paddle gets a file path (avoids oneDNN crash)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        pil_image.save(tmp_path, "PNG")

        # ── Step 1: PaddleOCR ────────────────────────────────────────────────
        paddle_text, paddle_elements, paddle_conf = _run_paddle(tmp_path)
        print(
            f"[OCR] Paddle confidence: {paddle_conf:.3f} "
            f"({len(paddle_elements)} tokens)"
        )

        if not _TESSERACT_AVAILABLE:
            # Tesseract not installed – return Paddle result as-is
            return paddle_text, paddle_elements, paddle_conf, "paddle_only"

        # ── Step 2: decide whether to try Tesseract ──────────────────────────
        if paddle_conf >= OCR_CONFIDENCE_THRESHOLD:
            print(f"[OCR] Paddle confidence sufficient → using Paddle result.")
            return paddle_text, paddle_elements, paddle_conf, "paddle"

        # ── Step 3: Tesseract fallback ───────────────────────────────────────
        print(
            f"[OCR] Paddle confidence {paddle_conf:.3f} < {OCR_CONFIDENCE_THRESHOLD} "
            f"→ trying Tesseract …"
        )
        tess_text, tess_elements, tess_conf = _run_tesseract(pil_image)
        print(
            f"[OCR] Tesseract confidence: {tess_conf:.3f} "
            f"({len(tess_elements)} tokens)"
        )

        # ── Step 4: pick the better result ───────────────────────────────────
        if tess_conf >= paddle_conf:
            print(f"[OCR] Tesseract wins (conf {tess_conf:.3f} ≥ {paddle_conf:.3f})")
            engine_used = "tesseract"
            return tess_text, tess_elements, tess_conf, engine_used
        else:
            print(
                f"[OCR] Paddle still wins (conf {paddle_conf:.3f} > {tess_conf:.3f}) "
                f"after Tesseract attempt."
            )
            engine_used = "paddle"
            return paddle_text, paddle_elements, paddle_conf, engine_used

    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
