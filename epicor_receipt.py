"""
epicor_receipt.py - EPICOR ERP On-Premise Receipt Entry & Attachment Module
Provides methods for:
1. Generating EPICOR DMT (Data Migration Tool) CSV files for Receipt Entry (GRN)
2. Saving scanned document evidence to EPICOR Shared Network Folder
3. Generating audit receipt summaries
"""

import os
import csv
import datetime
from PIL import Image

def save_to_epicor_network_share(pil_images: list, po_number: str, doc_type: str, share_folder: str) -> str:
    """
    Saves document image/PDF evidence directly to EPICOR Shared Network Folder.
    Returns the network UNC path for EPICOR Attachment linking.
    """
    if not share_folder or not os.path.exists(share_folder):
        # Fallback to local reports/epicor_attachments if network share not configured yet
        share_folder = os.path.join(os.path.dirname(__file__), "reports", "epicor_attachments")
    
    try:
        os.makedirs(share_folder, exist_ok=True)
    except Exception as e:
        print(f"[Warning] Could not create share folder {share_folder}: {e}")
        
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_po = str(po_number).replace(" ", "_")
    safe_type = doc_type.replace(" ", "_").replace("(", "").replace(")", "").replace("/", "-")
    
    filename = f"PO_{safe_po}_{safe_type}_{ts}.png"
    filepath = os.path.join(share_folder, filename)
    
    if pil_images:
        pil_images[0].save(filepath, "PNG")
        
    return filepath


def generate_epicor_dmt_receipt_csv(docs: list, po_number: str, output_path: str) -> str:
    """
    Generates an EPICOR DMT (Data Migration Tool) compatible CSV file for 
    Receipt Entry (RcvHead / RcvDtl). This allows 1-click batch receipt posting into EPICOR ERP.
    """
    try:
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
    except Exception as e:
        print(f"[Warning] Could not create report directory: {e}")
    
    # Extract fields from PO document if available
    po_doc = next((d for d in docs if d["type"] == "Purchase Order"), None)
    po_ext = po_doc["extraction"] if po_doc else None
    
    company = "100" # Default EPICOR Company ID
    vendor_name = getattr(po_ext, "supplier_name", None) if po_ext else "SUPPLIER"
    part_num = getattr(po_ext, "part_number", None) if po_ext else "PART-001"
    qty = getattr(po_ext, "quantity", None) if po_ext else "1"
    unit_price = getattr(po_ext, "unit_price", None) if po_ext else "0.0"
    receipt_date = datetime.datetime.now().strftime("%Y-%m-%d")
    
    rows = [
        {
            "Company": company,
            "PONum": po_number or "12345",
            "VendorID": vendor_name,
            "ReceiptDate": receipt_date,
            "PartNum": part_num,
            "ReceivedQty": qty,
            "DocUnitPrice": unit_price,
            "WarehouseCode": "MAIN",
            "BinNum": "BIN-AL-A01",
            "ReceiptType": "P",  # Purchase Receipt
            "PackSlip": f"PS-{datetime.datetime.now().strftime('%Y%m%d%H%M')}",
            "InspectionStatus": "APPROVED"
        }
    ]
    
    headers = list(rows[0].keys())
    
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)
        
    return output_path
