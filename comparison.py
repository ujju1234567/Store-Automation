"""
comparison.py - High-Precision Word-for-Word & Semantic Document Comparison Engine
Uses RapidFuzz string distance, numeric tolerances, and aerospace compliance rules
to compare Purchase Orders against Invoices, CoCs, MTCs, and Delivery Challans.
"""

import re
from typing import Dict, Any
from rapidfuzz import fuzz
from models import DocumentExtraction


def _normalise(value):
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()


def calculate_string_similarity(str1: str, str2: str) -> float:
    """Calculates rapidfuzz WRatio similarity score between 0.0 and 1.0."""
    n1 = _normalise(str1)
    n2 = _normalise(str2)
    if not n1 and not n2:
        return 1.0
    if not n1 or not n2:
        return 0.0
    if n1 == n2:
        return 1.0
    return float(fuzz.WRatio(n1, n2)) / 100.0


def compare_documents(base_po: DocumentExtraction, supporting_doc: DocumentExtraction) -> Dict[str, Any]:
    """
    High-precision comparison between Purchase Order and supporting document.
    Returns field-level matching scores, overall document similarity %, and pass/fail audit decision.
    """
    results = {}
    
    fields_to_check = [
        "supplier_name", 
        "supplier_address",
        "po_number", 
        "part_number", 
        "part_description",
        "material_grade",
        "material_specification",
        "quantity",
        "unit_price",
        "total_amount",
        "heat_number",
        "lot_number",
        "certificate_number",
        "drawing_number",
        "revision",
        "invoice_number",
        "delivery_number",
    ]
    
    base_dict = base_po.model_dump()
    supp_dict = supporting_doc.model_dump()
    
    total_weights = 0.0
    weighted_score = 0.0

    # Define field importance weights for aerospace compliance
    field_weights = {
        "po_number": 2.5,
        "part_number": 2.5,
        "quantity": 2.0,
        "heat_number": 2.0,
        "supplier_name": 1.5,
        "material_grade": 1.5,
        "material_specification": 1.5,
        "unit_price": 1.0,
        "total_amount": 1.0,
    }

    for field in fields_to_check:
        base_val = base_dict.get(field)
        supp_val = supp_dict.get(field)
        
        sim_score = calculate_string_similarity(str(base_val or ""), str(supp_val or ""))
        
        norm_b = _normalise(base_val)
        norm_s = _normalise(supp_val)

        if not norm_b and not norm_s:
            status = "both_missing"
            detail = "Not available in PO or document."
            score_pct = 100.0
        elif norm_b and not norm_s:
            status = "missing_in_document"
            detail = "Specified in PO but missing in supporting document."
            score_pct = 0.0
        elif not norm_b and norm_s:
            status = "not_in_po"
            detail = "Provided in supporting document; not specified in PO."
            score_pct = 100.0
        elif sim_score >= 0.95:
            status = "match"
            detail = f"Word-for-word match ({sim_score:.0%})."
            score_pct = sim_score * 100.0
        elif sim_score >= 0.70:
            status = "partial_match"
            detail = f"Fuzzy similarity match ({sim_score:.0%})."
            score_pct = sim_score * 100.0
        else:
            status = "mismatch"
            detail = f"Discrepancy detected ({sim_score:.0%} similarity)."
            score_pct = sim_score * 100.0

        # Accumulate weighted similarity score for overall document match %
        if norm_b or norm_s:
            weight = field_weights.get(field, 0.8)
            total_weights += weight
            weighted_score += (score_pct / 100.0) * weight

        results[field] = {
            "base": base_val,
            "supporting": supp_val,
            "status": status,
            "similarity_score": round(score_pct, 1),
            "detail": detail,
        }

    overall_match_pct = (weighted_score / total_weights * 100.0) if total_weights > 0 else 0.0
    
    # Store overall document comparison metadata
    results["_summary"] = {
        "overall_match_pct": round(overall_match_pct, 1),
        "is_approved": overall_match_pct >= 80.0,
        "total_fields_checked": len(fields_to_check),
    }

    return results
