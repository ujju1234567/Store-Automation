import os
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.environ["FLAGS_enable_pir_api"] = "0"
os.environ["FLAGS_use_mkldnn"] = "0"

import streamlit as st
import tempfile
from PIL import Image

st.set_page_config(page_title="Incoming Goods Inspection", layout="wide", page_icon="🏭")

# ─── Module imports (env vars must be set before paddle loads) ────────────────
import config
from utils import pdf_to_images, draw_ocr_boxes
from ocr import perform_ocr, ocr_engine
from extractor import extract_fields, HAS_GENAI
from comparison import compare_documents
from report import export_excel, export_pdf, export_json, export_raw_text_excel

# Clear results created by older OCR/parser versions so stale empty values are
# never shown after an application update.
PROCESSING_VERSION = 3
if st.session_state.get("processing_version") != PROCESSING_VERSION:
    st.session_state.processing_version = PROCESSING_VERSION
    st.session_state.step = 0
    st.session_state.docs = []

# ─── Session state ────────────────────────────────────────────────────────────
if 'step' not in st.session_state:
    st.session_state.step = 0
if 'docs' not in st.session_state:
    st.session_state.docs = []


# ─── Core processing ──────────────────────────────────────────────────────────
def process_file(uploaded_file, doc_type):
    """Process an uploaded file: render pages → OCR → semantic extract."""
    if uploaded_file is None:
        return None

    ext = os.path.splitext(uploaded_file.name)[1].lower()

    # Write the upload to a named temp file (needed for PDF rendering)
    with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
        tmp.write(uploaded_file.read())
        tmp_path = tmp.name

    try:
        if ext == ".pdf":
            images = pdf_to_images(tmp_path, dpi=config.PDF_DPI)
        else:
            with Image.open(tmp_path) as img:
                images = [img.copy().convert("RGB")]
    finally:
        # Release the temp file immediately after opening
        try:
            os.unlink(tmp_path)
        except Exception:
            pass

    all_text   = ""
    all_elements = []
    total_conf   = 0.0

    for i, img in enumerate(images):
        text, elements, conf = perform_ocr(img)
        all_text += f"\n--- Page {i+1} ---\n{text}"
        all_elements.extend(elements)
        total_conf += conf

    overall_conf = (total_conf / len(images)) if images else 0.0

    # Gemini semantic extraction (optional - gracefully fails if quota hit)
    extraction = extract_fields(all_text)

    return {
        "type":       doc_type,
        "images":     images,
        "raw_text":   all_text,
        "elements":   all_elements,
        "confidence": overall_conf,
        "extraction": extraction,
    }


# ─── Navigation helpers ───────────────────────────────────────────────────────
def next_step():
    st.session_state.step += 1

def reset():
    st.session_state.step = 0
    st.session_state.docs = []


# ─── UI ───────────────────────────────────────────────────────────────────────
st.title("🏭 AI-Powered Incoming Goods Inspection")
st.markdown("Automate verification of supplier documents against Purchase Orders using AI and PaddleOCR.")

if not HAS_GENAI or not config.GEMINI_API_KEY:
    st.warning("⚠️ Gemini API key not set – semantic field extraction disabled. OCR text export still works.")

# Document upload wizard
doc_types = [
    "Purchase Order",
    "Invoice",
    "Certificate of Conformance (CoC)",
    "Mill Test Certificate (MTC)",
    "Delivery Challan",
]

if st.session_state.step < len(doc_types):
    current_doc_type = doc_types[st.session_state.step]

    st.header(f"Step {st.session_state.step + 1} of {len(doc_types)}: {current_doc_type}")

    uploaded_file = st.file_uploader(
        f"Upload {current_doc_type} (PDF / PNG / JPG)",
        type=["pdf", "png", "jpg", "jpeg"],
        key=f"file_{st.session_state.step}",
    )

    col_btn, col_skip = st.columns([2, 8])

    with col_btn:
        if st.button("✅ Process & Next", type="primary"):
            if uploaded_file:
                with st.spinner(f"Running PaddleOCR on {current_doc_type}…"):
                    doc_data = process_file(uploaded_file, current_doc_type)
                if doc_data:
                    st.session_state.docs.append(doc_data)
                    n_lines = len(doc_data["elements"])
                    st.success(f"✓ OCR complete – {n_lines} text elements extracted from {current_doc_type}.")
                next_step()
                st.rerun()
            else:
                st.warning("Please upload a file first, or click 'Skip' to move on.")

    with col_skip:
        if st.session_state.step > 0:      # PO is mandatory
            if st.button("⏭ Skip this document"):
                next_step()
                st.rerun()

else:
    # ── Results page ──────────────────────────────────────────────────────────
    st.header("📋 Inspection Results")

    col_r, col_s = st.columns([2, 8])
    with col_r:
        if st.button("🔄 Start Over"):
            reset()
            st.rerun()

    if not st.session_state.docs:
        st.error("No documents were uploaded.")
        st.stop()

    po_doc = next((d for d in st.session_state.docs if d["type"] == "Purchase Order"), None)

    # ── 1. Raw OCR text dump (always works, no Gemini needed) ─────────────────
    st.markdown("### 📥 Raw OCR Text Export")

    report_dir = os.path.join(os.path.dirname(__file__), "reports")
    os.makedirs(report_dir, exist_ok=True)
    raw_excel_path = os.path.join(report_dir, "all_raw_text.xlsx")

    txt_path = export_raw_text_excel(st.session_state.docs, raw_excel_path)

    col_e, col_t = st.columns(2)
    with col_e:
        with open(raw_excel_path, "rb") as f:
            st.download_button(
                "📊 Download OCR Text (Excel)",
                f,
                file_name="all_raw_text.xlsx",
                type="primary",
            )
    with col_t:
        with open(txt_path, "rb") as f:
            st.download_button(
                "📄 Download OCR Text (TXT)",
                f,
                file_name="all_raw_text.txt",
            )

    # Show a quick preview of extracted text
    st.markdown("#### 🔍 OCR Text Preview")
    for doc in st.session_state.docs:
        with st.expander(f"📄 {doc['type']} — {len(doc['elements'])} lines extracted (confidence: {doc['confidence']:.1%})"):
            metric_a, metric_b, metric_c = st.columns(3)
            metric_a.metric("Text elements", len(doc["elements"]))
            metric_b.metric("OCR confidence", f"{doc['confidence']:.1%}")
            metric_c.metric("Pages", len(doc["images"]))
            if doc["elements"]:
                st.code(doc["raw_text"], language=None)
            else:
                st.error("PaddleOCR returned no text for this document. Re-scan at a higher resolution or verify that the pages contain readable text.")

            extracted = {
                field.replace("_", " ").title(): value
                for field, value in doc["extraction"].model_dump().items()
                if value not in (None, "")
            }
            st.markdown("**Extracted document details**")
            if extracted:
                st.json(extracted)
            else:
                st.warning("No labeled fields were found. The raw OCR text above is the source used for comparison.")

    # ── 2. Cross-reference (requires both PO and a supporting doc) ───────────
    if po_doc:
        supporting_docs = [d for d in st.session_state.docs if d["type"] != "Purchase Order"]
        if supporting_docs:
            st.markdown("### 🔍 Cross-Reference Verification")
            for supp_doc in supporting_docs:
                st.subheader(f"PO vs {supp_doc['type']}")
                results = compare_documents(po_doc["extraction"], supp_doc["extraction"])
                for field, data in results.items():
                    status = data["status"]
                    icon   = "✅" if status == "match" else "❌" if "mismatch" in status else "⚠️"
                    st.markdown(
                        f"**{field.replace('_', ' ').title()}**: {icon} {data['detail']} "
                        f"(PO: *{data['base'] or 'Not found'}* | Doc: *{data['supporting'] or 'Not found'}*)"
                    )

                # Bounding box visualization
                if supp_doc["images"]:
                    with st.expander(f"🖼️ View bounding boxes on {supp_doc['type']}"):
                        boxes = [
                            el["box"] for el in supp_doc["elements"]
                            if el.get("box") is not None and len(el["box"]) > 0
                        ]
                        img_boxes = draw_ocr_boxes(supp_doc["images"][0], boxes)
                        st.image(img_boxes, width="stretch")

                # Comparison Excel export
                excel_path = os.path.join(
                    report_dir,
                    f"comparison_{supp_doc['type'].replace(' ', '_').replace('(', '').replace(')', '')}.xlsx"
                )
                export_excel(results, excel_path)
                with open(excel_path, "rb") as f:
                    st.download_button(
                        f"📊 Download Comparison: {supp_doc['type']}",
                        f,
                        file_name=os.path.basename(excel_path),
                    )
