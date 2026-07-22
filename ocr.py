import os
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.environ["FLAGS_enable_pir_api"] = "0"
os.environ["FLAGS_use_mkldnn"] = "0"

import tempfile
import numpy as np
from PIL import Image
from paddleocr import PaddleOCR

# Initialize PaddleOCR - identical settings to the original working paddle_app.py
print("Initializing PaddleOCR in ocr.py...")
ocr_engine = PaddleOCR(
    lang="en",
    ocr_version="PP-OCRv4",
    device="cpu",
    enable_mkldnn=False,
    use_doc_orientation_classify=False,
    use_doc_unwarping=False,
    use_textline_orientation=False,
)
print("PaddleOCR ready.")


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
        return list(value)
    return [value]


def perform_ocr(pil_image: Image.Image):
    """
    Run OCR on a PIL Image.
    Saves to a temp PNG file and passes the FILE PATH to predict(),
    which is the exact same approach as the original working paddle_app.py.

    Returns:
      - full_text (str)
      - elements (list of dicts: {text, confidence, box})
      - overall_confidence (float)
    """
    # Save PIL image to a temp PNG file - this is the KEY fix.
    # Passing numpy arrays to predict() triggers oneDNN which crashes.
    tmp_path = None
    elements = []
    full_text_lines = []
    total_conf = 0.0

    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp_path = tmp.name
        pil_image.save(tmp_path, "PNG")

        # Call predict() with a file PATH - exactly like paddle_app.py did
        results = ocr_engine.predict(tmp_path)

        for result in results:
            texts = _as_list(_result_value(result, "rec_texts"))
            scores = _as_list(_result_value(result, "rec_scores"))
            boxes = _as_list(_result_value(result, "dt_polys"))
            if not boxes:
                boxes = _as_list(_result_value(result, "dt_boxes"))

            # PaddleOCR may omit scores or boxes for a result; keep the text.
            scores.extend([1.0] * (len(texts) - len(scores)))
            boxes.extend([[]] * (len(texts) - len(boxes)))

            for text, conf, box in zip(texts, scores, boxes):
                if text and text.strip():
                    elements.append({
                        "text":       text,
                        "confidence": float(conf),
                        "box":        box,
                    })
                    full_text_lines.append(text)
                    total_conf += float(conf)

    except Exception as e:
        print(f"[OCR ERROR] {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    full_text = "\n".join(full_text_lines)
    overall_confidence = (total_conf / len(elements)) if elements else 0.0
    return full_text, elements, overall_confidence
