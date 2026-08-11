import os
import streamlit as st

# Environment Setup for PaddleOCR (must be set before imports)
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.environ["FLAGS_enable_pir_api"] = "0"
os.environ["FLAGS_use_mkldnn"] = "0"

# Gemini API Key (set it in the environment when AI enrichment is needed)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
ENABLE_AI_EXTRACTION = False

# Other Settings
PDF_DPI = 120
CONFIDENCE_THRESHOLD_WARNING = 0.85
CONFIDENCE_THRESHOLD_DANGER = 0.60

# ── Adaptive dual-engine OCR settings ────────────────────────────────────────
# If PaddleOCR's mean confidence falls below this value, Tesseract is also run
# and the higher-confidence result is kept.  Range: 0.0 – 1.0.
OCR_CONFIDENCE_THRESHOLD = 0.80

# Optional: explicit path to the Tesseract binary (leave empty for auto-detect)
TESSERACT_PATH = os.getenv("TESSERACT_PATH", "")
