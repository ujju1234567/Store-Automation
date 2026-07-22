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
