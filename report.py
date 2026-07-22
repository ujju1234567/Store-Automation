import json
import pandas as pd
from fpdf import FPDF
from typing import Dict, Any, List


def export_json(results: Dict[str, Any], filepath: str):
    """Export comparison results to JSON."""
    with open(filepath, 'w') as f:
        json.dump(results, f, indent=4)


def export_excel(results: Dict[str, Any], filepath: str):
    """Export comparison results to Excel."""
    rows = []
    for field, data in results.items():
        rows.append({
            "Field": field.replace('_', ' ').title(),
            "Purchase Order Value": data.get("base", "") or "",
            "Supporting Doc Value": data.get("supporting", "") or "",
            "Status": data.get("status", "").replace('_', ' ').title()
        })
    df = pd.DataFrame(rows)
    df.to_excel(filepath, index=False)


def export_raw_text_excel(docs_data: List[Dict[str, Any]], filepath: str):
    """
    Export ALL raw OCR text from every uploaded document to an Excel file.
    Each document gets its own sheet. Also writes a combined .txt file alongside.
    """
    # Write Excel with one sheet per document
    with pd.ExcelWriter(filepath, engine='openpyxl') as writer:
        for doc in docs_data:
            doc_type = doc.get("type", "Unknown")
            raw_text = doc.get("raw_text", "") or ""
            confidence = doc.get("confidence", 0.0)
            elements   = doc.get("elements", [])

            # Sheet 1: line-by-line text with confidence
            rows = []
            for el in elements:
                rows.append({
                    "Text":       el.get("text", ""),
                    "Confidence": round(el.get("confidence", 0.0), 4),
                })
            if not rows:
                rows = [{"Text": "(No text extracted)", "Confidence": 0.0}]

            df = pd.DataFrame(rows)
            sheet_name = doc_type[:28].replace("/", "-").replace("\\", "-")  # Excel sheet name limit
            df.to_excel(writer, sheet_name=sheet_name, index=False)

    # Also write a plain text file alongside
    txt_path = filepath.replace(".xlsx", ".txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        for doc in docs_data:
            doc_type = doc.get("type", "Unknown")
            raw_text = doc.get("raw_text", "") or ""
            confidence = doc.get("confidence", 0.0)
            f.write("=" * 60 + "\n")
            f.write(f"DOCUMENT: {doc_type}\n")
            f.write(f"Overall OCR Confidence: {confidence:.2%}\n")
            f.write("=" * 60 + "\n")
            f.write(raw_text if raw_text.strip() else "(No text extracted)\n")
            f.write("\n\n")

    return txt_path


def export_pdf(results: Dict[str, Any], filepath: str):
    """Export comparison results to a professional PDF."""
    pdf = FPDF()
    pdf.add_page()

    pdf.set_font("helvetica", "B", 16)
    pdf.cell(0, 10, "Incoming Goods Inspection Report", ln=True, align='C')
    pdf.ln(10)

    pdf.set_font("helvetica", "B", 12)
    col_widths = [45, 60, 60, 25]
    headers = ["Field", "Purchase Order", "Supporting Doc", "Status"]
    for i, header in enumerate(headers):
        pdf.cell(col_widths[i], 10, header, border=1, align='C')
    pdf.ln()

    pdf.set_font("helvetica", "", 10)
    for field, data in results.items():
        field_name = field.replace('_', ' ').title()
        base_val   = str(data.get("base") or "")
        supp_val   = str(data.get("supporting") or "")
        status     = str(data.get("status", "")).replace('_', ' ').title()

        pdf.cell(col_widths[0], 10, field_name[:25], border=1)
        pdf.cell(col_widths[1], 10, base_val[:35],   border=1)
        pdf.cell(col_widths[2], 10, supp_val[:35],   border=1)

        if status == "Match":
            pdf.set_text_color(0, 128, 0)
        elif "Mismatch" in status:
            pdf.set_text_color(255, 0, 0)
        elif "Missing" in status:
            pdf.set_text_color(255, 165, 0)
        else:
            pdf.set_text_color(0, 0, 0)

        pdf.cell(col_widths[3], 10, status, border=1, align='C')
        pdf.set_text_color(0, 0, 0)
        pdf.ln()

    pdf.output(filepath)
