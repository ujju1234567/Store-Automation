from models import DocumentExtraction
from typing import Dict, Any
import re


def _normalise(value):
    if value is None:
        return ""
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())

def compare_documents(base_po: DocumentExtraction, supporting_doc: DocumentExtraction) -> Dict[str, Any]:
    """
    Compares a supporting document (like Invoice, CoC) against the base PO.
    Returns a dictionary of comparisons with status ('match', 'mismatch', 'missing').
    """
    results = {}
    
    # Compare all shared business identifiers. Document-specific identifiers
    # remain useful as evidence but are not expected to exist in the PO.
    fields_to_check = [
        "supplier_name", 
        "supplier_address",
        "po_number", 
        "part_number", 
        "material_grade",
        "material_specification",
        "quantity",
        "heat_number",
        "lot_number",
        "certificate_number",
        "drawing_number",
        "revision",
        "issue_date",
        "delivery_number",
        "invoice_number",
        "customer_name",
    ]
    
    base_dict = base_po.model_dump()
    supp_dict = supporting_doc.model_dump()
    
    for field in fields_to_check:
        base_val = base_dict.get(field)
        supp_val = supp_dict.get(field)
        norm_base = _normalise(base_val)
        norm_supp = _normalise(supp_val)

        status = "both_missing"
        detail = "Not available in the PO or document."
        if norm_base and not norm_supp:
            status = "missing_in_document"
            detail = "Available in PO but not found in this document."
        elif not norm_base and norm_supp:
            status = "not_in_po"
            detail = "Not available in PO; document provides a value."
        elif norm_base == norm_supp and norm_base:
            status = "match"
            detail = "Matches PO."
        elif norm_base in norm_supp or norm_supp in norm_base:
            status = "partial_match"
            detail = "Partially matches PO."
        elif norm_base and norm_supp:
            status = "mismatch"
            detail = "Does not match PO."

        results[field] = {
            "base": base_val,
            "supporting": supp_val,
            "status": status,
            "detail": detail,
        }
        
    return results
