import os
import re
from config import GEMINI_API_KEY, ENABLE_AI_EXTRACTION
from models import DocumentExtraction
import json

try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

# Models to try in order if one fails/is rate-limited
GEMINI_MODELS = [
    "gemini-1.5-flash",
    "gemini-1.5-flash-latest",
    "gemini-1.0-pro",
]


def _first_match(text, patterns):
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            value = match.group(1).strip(" :#-\t")
            if value:
                return value
    return None


def extract_fields_locally(ocr_text: str) -> DocumentExtraction:
    """Extract common document identifiers without requiring an AI API."""
    text = ocr_text or ""
    values = {
        "supplier_name": _first_match(text, [
            r"(?:supplier|vendor|seller)[ \t]*(?:name)?[ \t]*[:#-][ \t]*([^\r\n]+)",
        ]),
        "po_number": _first_match(text, [
            r"(?:purchase\s*order|p\.?o\.?)\s*(?:number|no\.?)?\s*[:#-]?\s*([A-Z0-9][A-Z0-9 /_-]{2,})",
        ]),
        "part_number": _first_match(text, [
            r"(?:part\s*(?:number|no\.?)|item\s*number|catalog(?:ue)?\s*(?:number|no\.?)?)[ \t]*[:#-][ \t]*([^\r\n]+)",
        ]),
        "material_grade": _first_match(text, [
            r"(?:material\s*grade|grade)[ \t]*[:#-][ \t]*([^\r\n]+)",
        ]),
        "material_specification": _first_match(text, [
            r"(?:material\s*specification|material\s*spec|specification)[ \t]*[:#-][ \t]*([^\r\n]+)",
        ]),
        "quantity": _first_match(text, [
            r"quantity[ \t]*[:#-]?[ \t]*([0-9][0-9,.]*(?:[ \t]*[A-Za-z]+)?)",
        ]),
        "heat_number": _first_match(text, [
            r"(?:heat|cast)[ \t]*(?:number|no\.?)?[ \t]*[:#-][ \t]*([^\r\n]+)",
        ]),
        "lot_number": _first_match(text, [
            r"lot[ \t]*(?:number|no\.?)?[ \t]*[:#-][ \t]*([^\r\n]+)",
        ]),
        "certificate_number": _first_match(text, [
            r"(?:certificate|cert\.?)\s*(?:number|no\.?)?[ \t]*[:#-][ \t]*([^\r\n]+)",
        ]),
        "drawing_number": _first_match(text, [
            r"drawing[ \t]*(?:number|no\.?)?[ \t]*[:#-][ \t]*([^\r\n]+)",
        ]),
        "revision": _first_match(text, [
            r"revision[ \t]*[:#-][ \t]*([^\r\n]+)",
        ]),
        "issue_date": _first_match(text, [
            r"(?:issue|document)[ \t]*date[ \t]*[:#-][ \t]*([^\r\n]+)",
        ]),
        "delivery_number": _first_match(text, [
            r"(?:delivery|challan)[ \t]*(?:number|no\.?)?[ \t]*[:#-][ \t]*([^\r\n]+)",
        ]),
        "invoice_number": _first_match(text, [
            r"invoice[ \t]*(?:number|no\.?)?[ \t]*[:#-][ \t]*([^\r\n]+)",
        ]),
        "customer_name": _first_match(text, [
            r"(?:customer|buyer)[ \t]*(?:name)?[ \t]*[:#-][ \t]*([^\r\n]+)",
        ]),
    }
    return DocumentExtraction(**values)


def _merge_extractions(local, remote):
    values = local.model_dump()
    for field, value in remote.model_dump().items():
        if value not in (None, ""):
            values[field] = value
    return DocumentExtraction(**values)

def extract_fields(ocr_text: str) -> DocumentExtraction:
    """
    Uses Gemini API to perform semantic extraction on the raw OCR text.
    Tries multiple models if one is unavailable or rate-limited.
    Returns a DocumentExtraction Pydantic object.
    """
    local_extraction = extract_fields_locally(ocr_text)

    if not ENABLE_AI_EXTRACTION:
        return local_extraction

    if not HAS_GENAI:
        print("Warning: google-genai not installed. Using local extraction.")
        return local_extraction

    if not GEMINI_API_KEY:
        print("Warning: GEMINI_API_KEY is not set. Using local extraction.")
        return local_extraction

    if not ocr_text or not ocr_text.strip():
        print("Warning: No OCR text to extract from.")
        return local_extraction

    prompt = f"""
You are an expert AI extraction system for aerospace manufacturing.
Extract structured information from the following OCR text of an Incoming Goods 
Inspection document (Purchase Order, Invoice, Certificate of Conformance, etc.).

Extract values for all fields. If a field is not present, use null.
Be accurate for Part Numbers, Quantities, and Material Specifications.

OCR TEXT:
\"\"\"
{ocr_text[:8000]}
\"\"\"
"""

    client = genai.Client(api_key=GEMINI_API_KEY)

    for model_name in GEMINI_MODELS:
        try:
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=DocumentExtraction,
                ),
            )
            data = json.loads(response.text)
            return _merge_extractions(local_extraction, DocumentExtraction(**data))
        except Exception as e:
            err = str(e)
            print(f"[Gemini {model_name}] Error: {err[:200]}")
            if "quota" in err.lower() or "rate" in err.lower() or "429" in err:
                print(f"  -> Rate limited on {model_name}, trying next model...")
                continue
            elif "404" in err or "not found" in err.lower():
                print(f"  -> Model {model_name} not available, trying next...")
                continue
            else:
                # Unexpected error - stop trying
                break

    print("All Gemini models failed or rate-limited. Using local extraction.")
    return local_extraction
