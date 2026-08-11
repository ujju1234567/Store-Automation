import os

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
OCR_CONFIDENCE_THRESHOLD = 0.80
TESSERACT_PATH = os.getenv("TESSERACT_PATH", "")

# ── Project Workspace Storage Paths (bypasses corporate DLP / encryption issues) ──
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE_DIR = os.path.join(BASE_DIR, "database")
SCANNER_INBOX_DIR = os.path.join(BASE_DIR, "scan_inbox")
TEMP_CACHE_DIR = os.path.join(BASE_DIR, "temp_cache")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")

for _d in [DATABASE_DIR, SCANNER_INBOX_DIR, TEMP_CACHE_DIR, REPORTS_DIR]:
    try:
        os.makedirs(_d, exist_ok=True)
    except Exception as _e:
        print(f"[Warning] Could not create directory {_d}: {_e}")
