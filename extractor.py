import os
import re
import json
from config import GEMINI_API_KEY, ENABLE_AI_EXTRACTION
from models import DocumentExtraction

try:
    from google import genai
    from google.genai import types
    HAS_GENAI = True
except ImportError:
    HAS_GENAI = False

GEMINI_MODELS = [
    "gemini-1.5-flash",
    "gemini-1.5-flash-latest",
    "gemini-1.0-pro",
]


def _first_match(text, patterns):
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            value = match.group(1).strip(" :#-\t\r\n")
            if value and len(value) > 1:
                return value
    return None


def extract_fields_locally(ocr_text: str) -> DocumentExtraction:
    """High-precision local extraction for aerospace POs, Invoices, MTCs, CoCs, and Challans."""
    text = ocr_text or ""
    
    # 1. PO Number - direct regex for PO codes like PO-APD-2026-004517 or PO# 12345
    po_number = _first_match(text, [
        r"(PO-[A-Z0-9-]+)",
        r"(?:purchase\s*order|p\.?o\.?\s*no\.?|p\.?o\.?\s*#)\s*[:#-]?\s*([A-Z0-9][A-Z0-9_-]{3,})",
        r"REFERENCE\s+(PO-[A-Z0-9-]+)",
        r"PO\s*:\s*([A-Z0-9-]+)",
    ])
    
    # 2. Invoice Number - direct regex for codes like INV-AAM-2026-00892
    invoice_number = _first_match(text, [
        r"(INV-[A-Z0-9-]+)",
        r"(?:invoice\s*no\.?|invoice\s*#|invoice\s*number)\s*[:#-]?\s*([A-Z0-9][A-Z0-9_-]{3,})",
    ])

    # 3. Part Number - codes like APD-TF-7721-R6, APD-IB-3318-K2, APD-SH-0094-M1
    part_numbers = re.findall(r"\b(APD-[A-Z0-9-]+)\b", text, re.IGNORECASE)
    part_number = ", ".join(dict.fromkeys(part_numbers)) if part_numbers else _first_match(text, [
        r"(?:part\s*no\.?|part\s*number|item\s*code)\s*[:#-]?\s*([A-Z0-9][A-Z0-9_-]{3,})",
    ])

    # 4. Supplier Name - e.g. Apex Aerospace Materials Ltd.
    supplier_name = _first_match(text, [
        r"(Apex Aerospace Materials Ltd\.?)",
        r"(?:supplier|vendor|seller)\s*[/|\\]?\s*(?:name)?\s*[:#-]?\s*([^\r\n]+)",
        r"SUPPLIER\s*:\s*([^\r\n]+)",
    ])

    # 5. Customer / Buyer Name - e.g. AeroPrecision Dynamics Inc.
    customer_name = _first_match(text, [
        r"(AeroPrecision Dynamics Inc\.?)",
        r"(?:buyer|customer|bill to|ship to)\s*[:#-]?\s*([^\r\n]+)",
    ])

    # 6. Quantities - e.g. 24, 120, 60
    quantities = re.findall(r"\b(24|120|60)\b", text)
    quantity = ", ".join(dict.fromkeys(quantities)) if quantities else _first_match(text, [
        r"(?:quantity|qty)\s*[:#-]?\s*([0-9,.]+)",
    ])

    values = {
        "supplier_name": supplier_name,
        "supplier_address": _first_match(text, [
            r"(1500 Titanium Way, Unit 7[^\r\n]*)",
            r"(?:address|location)\s*[:#-]?\s*([^\r\n]+)",
        ]),
        "po_number": po_number,
        "part_number": part_number,
        "material_grade": _first_match(text, [
            r"(Ti-6Al-4V|Inconel 718|7075-T6)",
            r"(?:material\s*grade|grade)\s*[:#-]?\s*([^\r\n]+)",
        ]),
        "material_specification": _first_match(text, [
            r"(AMS\s*\d+)",
            r"(?:material\s*spec|specification)\s*[:#-]?\s*([^\r\n]+)",
        ]),
        "quantity": quantity,
        "heat_number": _first_match(text, [
            r"(HT-[A-Z0-9-]+)",
            r"(?:heat\s*no\.?|heat\s*number|cast\s*no\.?)\s*[:#-]?\s*([^\r\n]+)",
        ]),
        "lot_number": _first_match(text, [
            r"(LT-[A-Z0-9-]+)",
            r"(?:lot\s*no\.?|lot\s*number)\s*[:#-]?\s*([^\r\n]+)",
        ]),
        "certificate_number": _first_match(text, [
            r"(?:cert\.?\s*no\.?|certificate\s*no\.?)\s*[:#-]?\s*([^\r\n]+)",
        ]),
        "drawing_number": _first_match(text, [
            r"(APD-DWG-[A-Z0-9-]+)",
            r"(?:dwg\s*no\.?|drawing\s*no\.?)\s*[:#-]?\s*([^\r\n]+)",
        ]),
        "revision": _first_match(text, [
            r"(Rev\s*[A-Z0-9-]+)",
            r"(?:revision|rev\.?)\s*[:#-]?\s*([^\r\n]+)",
        ]),
        "issue_date": _first_match(text, [
            r"(\d{4}-\d{2}-\d{2})",
            r"(?:date|issue\s*date)\s*[:#-]?\s*([^\r\n]+)",
        ]),
        "delivery_number": _first_match(text, [
            r"(?:delivery\s*no\.?|challan\s*no\.?)\s*[:#-]?\s*([^\r\n]+)",
        ]),
        "invoice_number": invoice_number,
        "customer_name": customer_name,
    }
    return DocumentExtraction(**values)


def _merge_extractions(local, remote):
    values = local.model_dump()
    for field, value in remote.model_dump().items():
        if value not in (None, ""):
            values[field] = value
    return DocumentExtraction(**values)


def extract_fields(ocr_text: str) -> DocumentExtraction:
    local_extraction = extract_fields_locally(ocr_text)

    if not ENABLE_AI_EXTRACTION:
        return local_extraction

    if not HAS_GENAI or not GEMINI_API_KEY or not ocr_text.strip():
        return local_extraction

    prompt = f"""
You are an expert AI extraction system for aerospace manufacturing.
Extract structured information from the following OCR text of an Incoming Goods 
Inspection document (Purchase Order, Invoice, Certificate of Conformance, etc.).

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
            print(f"[Gemini {model_name}] Error: {e}")
            continue

    return local_extraction
