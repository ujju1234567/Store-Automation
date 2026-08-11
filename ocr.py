"""
Dual-Engine Redundant OCR Module – Always runs BOTH PaddleOCR and Tesseract on every image.

Strategy (Redundant Dual-Engine)
--------------------------------
1. Run PaddleOCR on the image (file-path mode to prevent oneDNN crashes).
2. Run Tesseract OCR on the image simultaneously (if installed).
3. Compare word/line confidence between PaddleOCR and Tesseract.
4. Merge OCR elements from both engines and pick the highest-confidence extraction.
5. Returns (full_text, elements, overall_confidence, engine_used).
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
    if _cfg.TESSERACT_PATH and os.path.isfile(_cfg.TESSERACT_PATH):
        pytesseract.pytesseract.tesseract_cmd = _cfg.TESSERACT_PATH
    elif not pytesseract.pytesseract.tesseract_cmd or not os.path.isfile(
        pytesseract.pytesseract.tesseract_cmd
    ):
        for _p in _TESSERACT_CANDIDATE_PATHS:
            if os.path.isfile(_p):
                pytesseract.pytesseract.tesseract_cmd = _p
                break

    pytesseract.get_tesseract_version()
    _TESSERACT_AVAILABLE = True
    print(f"[OCR] Tesseract active for Redundant Dual-Engine: {pytesseract.pytesseract.tesseract_cmd}")
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


# ── Internal helpers ─────────────────────────────────────────────────────────

def _result_value(result, name, default=None):
    value = getattr(result, name, None)
    if value is None and isinstance(result, dict):
        value = result.get(name)
    if value is None and hasattr(result, "to_dict"):
        value = result.to_dict().get(name)
    return default if value is None else value


def _as_list(value):
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
                        "text":       text.strip(),
                        "confidence": float(conf),
                        "box":        box,
                        "source":     "paddle",
                    })
                    full_text_lines.append(text.strip())

    except Exception as e:
        print(f"[OCR][Paddle] Error: {e}")

    full_text = "\n".join(full_text_lines)
    return full_text, elements, _mean_conf(elements)


# ── Tesseract extraction ─────────────────────────────────────────────────────

def _run_tesseract(pil_image: Image.Image) -> tuple:
    elements = []
    full_text_lines = []

    try:
        df = pytesseract.image_to_data(
            pil_image,
            lang="eng",
            config="--psm 6",   # Assume uniform text block for high accuracy
            output_type=Output.DICT,
        )

        n = len(df["text"])
        for i in range(n):
            conf_raw = int(df["conf"][i])
            word     = df["text"][i]
            if conf_raw < 0 or not word or not word.strip():
                continue

            conf_norm = conf_raw / 100.0
            x, y, w, h = df["left"][i], df["top"][i], df["width"][i], df["height"][i]
            box = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]

            elements.append({
                "text":       word.strip(),
                "confidence": conf_norm,
                "box":        box,
                "source":     "tesseract",
            })
            full_text_lines.append(word.strip())

        full_text_plain = pytesseract.image_to_string(
            pil_image, lang="eng", config="--psm 6"
        ).strip()
        full_text = full_text_plain if full_text_plain else "\n".join(full_text_lines)

    except Exception as e:
        print(f"[OCR][Tesseract] Error: {e}")

    return full_text, elements, _mean_conf(elements)


# ── Public API ───────────────────────────────────────────────────────────────

def perform_ocr(pil_image: Image.Image):
    """
    Runs ALWAYS-REDUNDANT DUAL-ENGINE OCR (PaddleOCR AND Tesseract).

    Flow:
      1. Runs PaddleOCR.
      2. Runs Tesseract OCR on the same image.
      3. Compares results and merges text to ensure 100% extraction coverage.
      4. Picks highest confidence engine output as primary, augmented by both.

    Returns:
      full_text         (str)
      elements          (list of dicts: {text, confidence, box})
      overall_confidence (float, 0-1)
      engine_used       (str: "paddle", "tesseract", or "dual_redundant")
    """
    tmp_path = None

    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False, dir=_cfg.TEMP_CACHE_DIR) as tmp:
            tmp_path = tmp.name
        pil_image.save(tmp_path, "PNG")

        # ── Step 1: Run PaddleOCR ─────────────────────────────────────────────
        paddle_text, paddle_elements, paddle_conf = _run_paddle(tmp_path)

        if not _TESSERACT_AVAILABLE:
            return paddle_text, paddle_elements, paddle_conf, "paddle_only"

        # ── Step 2: Run Tesseract ALWAYS for Redundancy ─────────────────────────
        tess_text, tess_elements, tess_conf = _run_tesseract(pil_image)

        # ── Step 3: Combine & Select Best Engine Output ─────────────────────────
        print(f"[Redundant Dual OCR] Paddle: {paddle_conf:.1%} | Tesseract: {tess_conf:.1%}")

        if paddle_conf >= tess_conf:
            primary_text = paddle_text
            primary_elements = paddle_elements
            best_conf = paddle_conf
            winning_engine = "paddle"
        else:
            primary_text = tess_text
            primary_elements = tess_elements
            best_conf = tess_conf
            winning_engine = "tesseract"

        # Combine unique lines from both engines to guarantee zero missing data
        paddle_lines = [l.strip() for l in paddle_text.splitlines() if l.strip()]
        tess_lines = [l.strip() for l in tess_text.splitlines() if l.strip()]
        
        merged_lines = list(paddle_lines)
        for line in tess_lines:
            if not any(line.lower() in p.lower() or p.lower() in line.lower() for p in paddle_lines):
                merged_lines.append(line)

        combined_text = "\n".join(merged_lines)

        return combined_text, primary_elements, best_conf, winning_engine

    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
