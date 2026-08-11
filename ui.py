import os
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"
os.environ["FLAGS_enable_pir_api"] = "0"
os.environ["FLAGS_use_mkldnn"] = "0"

import io
import datetime
import streamlit as st
import tempfile
from PIL import Image
from concurrent.futures import ThreadPoolExecutor, as_completed

st.set_page_config(page_title="Incoming Goods Inspection", layout="wide", page_icon="🏭")

# ─── Module imports ───────────────────────────────────────────────────────────
import config
from utils import pdf_to_images, draw_ocr_boxes
from ocr import perform_ocr
from extractor import extract_fields
from comparison import compare_documents
from report import export_excel, export_raw_text_excel

# ─── Styling ──────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    div[data-testid="stTabs"] button[data-baseweb="tab"] {
        font-size: 0.95rem;
        font-weight: 600;
        padding: 0.5rem 1.2rem;
    }
    .cam-instruction {
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 10px;
        padding: 0.8rem 1rem;
        font-size: 0.85rem;
        color: #a0aab4;
        margin-bottom: 0.8rem;
    }
    .folder-info {
        background: rgba(0, 180, 100, 0.08);
        border-left: 3px solid #00c853;
        border-radius: 6px;
        padding: 0.6rem 1rem;
        font-size: 0.85rem;
        margin-top: 0.5rem;
    }
    .step-badge {
        display: inline-block;
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        color: white;
        border-radius: 20px;
        padding: 0.2rem 0.8rem;
        font-size: 0.8rem;
        font-weight: 600;
        margin-bottom: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)

# ─── Processing version guard & session init ──────────────────────────────────
PROCESSING_VERSION = 5
if st.session_state.get("processing_version") != PROCESSING_VERSION:
    st.session_state.processing_version = PROCESSING_VERSION
    st.session_state.step = 0
    st.session_state.docs = []
    st.session_state.pending_items = []
    st.session_state.camera_db_folder = r"C:\Users\shailesh\Documents\InspectionImages"

if "step" not in st.session_state:
    st.session_state.step = 0
if "docs" not in st.session_state:
    st.session_state.docs = []
if "pending_items" not in st.session_state:
    st.session_state.pending_items = []
if "camera_db_folder" not in st.session_state:
    st.session_state.camera_db_folder = r"C:\Users\shailesh\Documents\InspectionImages"


# ─── File & Camera Saving Helpers ──────────────────────────────────────────────
def save_image_to_db(pil_image: Image.Image, doc_type: str, folder: str) -> str:
    """Save a PIL image to the target folder with timestamped filename."""
    os.makedirs(folder, exist_ok=True)
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_type = doc_type.replace(" ", "_").replace("(", "").replace(")", "").replace("/", "-")
    filename = f"{safe_type}_{ts}.png"
    filepath = os.path.join(folder, filename)
    pil_image.save(filepath, "PNG")
    return filepath


# Engine display labels / colours
_ENGINE_LABELS = {
    "paddle":      ("🟢 PaddleOCR",  "#00c853"),
    "tesseract":   ("🔵 Tesseract",  "#2196f3"),
    "paddle_only": ("🟢 PaddleOCR",  "#00c853"),
}


def _run_ocr_and_extract(images, doc_type):
    """Core OCR + field extraction for a list of images."""
    all_text = ""
    all_elements = []
    total_conf = 0.0
    engine_counts: dict = {}

    for i, img in enumerate(images):
        result = perform_ocr(img)
        # Support both old 3-tuple and new 4-tuple return
        if len(result) == 4:
            text, elements, conf, engine = result
        else:
            text, elements, conf = result
            engine = "paddle_only"

        all_text += f"\n--- Page {i+1} ---\n{text}"
        all_elements.extend(elements)
        total_conf += conf
        engine_counts[engine] = engine_counts.get(engine, 0) + 1

    overall_conf = (total_conf / len(images)) if images else 0.0
    # Primary engine = whichever engine handled most pages
    primary_engine = max(engine_counts, key=engine_counts.get) if engine_counts else "paddle_only"
    extraction = extract_fields(all_text)

    return {
        "type":        doc_type,
        "images":      images,
        "raw_text":    all_text,
        "elements":    all_elements,
        "confidence":  overall_conf,
        "extraction":  extraction,
        "engine":      primary_engine,
        "engine_counts": engine_counts,
    }


def process_single_item(item):
    """Processes a pending document (file or camera) through OCR."""
    doc_type = item["type"]
    input_type = item["input_type"]

    if input_type == "file":
        uploaded_file = item["file"]
        ext = os.path.splitext(uploaded_file.name)[1].lower()
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
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

        res = _run_ocr_and_extract(images, doc_type)
        res["source"] = "upload"
        res["saved_path"] = item.get("saved_path")
        return res

    else:
        # Camera
        pil_img = item["pil_img"]
        images = [pil_img.convert("RGB")]
        res = _run_ocr_and_extract(images, doc_type)
        res["source"] = "camera"
        res["saved_path"] = item.get("saved_path")
        return res


# ─── Navigation helpers ───────────────────────────────────────────────────────
def next_step():
    st.session_state.step += 1

def reset():
    st.session_state.step = 0
    st.session_state.docs = []
    st.session_state.pending_items = []


# ─── Header ───────────────────────────────────────────────────────────────────
st.title("🏭 AI-Powered Incoming Goods Inspection")
st.markdown("Automate verification of supplier documents against Purchase Orders using AI and PaddleOCR.")

doc_types = [
    "Purchase Order",
    "Invoice",
    "Certificate of Conformance (CoC)",
    "Mill Test Certificate (MTC)",
    "Delivery Challan",
]

# ─── Step-by-Step Document Collection Wizard ──────────────────────────────────
if st.session_state.step < len(doc_types):
    current_doc_type = doc_types[st.session_state.step]

    st.markdown(
        f'<div class="step-badge">Step {st.session_state.step + 1} of {len(doc_types)}</div>',
        unsafe_allow_html=True,
    )
    st.header(f"📄 {current_doc_type}")

    # ── Folder selection ONLY on Step 1 (Purchase Order) ─────────────────────
    if st.session_state.step == 0:
        st.markdown("### 📁 Image Database Storage Folder")
        st.markdown("Specify the folder path on your laptop where all clicked document images will be saved as a database.")
        
        folder_input = st.text_input(
            "Folder Path",
            value=st.session_state.camera_db_folder,
            placeholder=r"e.g. C:\Users\shailesh\Documents\InspectionImages",
            key="po_folder_input",
        )
        if folder_input.strip():
            st.session_state.camera_db_folder = folder_input.strip()
            try:
                os.makedirs(st.session_state.camera_db_folder, exist_ok=True)
                st.markdown(
                    f'<div class="folder-info">📂 Active DB Folder: <code>{st.session_state.camera_db_folder}</code></div>',
                    unsafe_allow_html=True,
                )
            except Exception as e:
                st.error(f"❌ Cannot access folder: {e}")
        st.divider()

    # ── Input mode tabs ────────────────────────────────────────────────────
    tab_upload, tab_camera = st.tabs(["📂 Upload File", "📷 Camera Capture"])

    # ── TAB 1: File Upload ─────────────────────────────────────────────────
    with tab_upload:
        uploaded_file = st.file_uploader(
            f"Upload {current_doc_type} (PDF / PNG / JPG)",
            type=["pdf", "png", "jpg", "jpeg"],
            key=f"file_{st.session_state.step}",
        )

        col_btn, col_skip = st.columns([2, 8])
        with col_btn:
            if st.button("✅ Process & Next", type="primary", key=f"process_upload_{st.session_state.step}"):
                if uploaded_file:
                    st.session_state.pending_items.append({
                        "type": current_doc_type,
                        "input_type": "file",
                        "file": uploaded_file,
                    })
                    st.toast(f"✅ {current_doc_type} saved for parallel processing!", icon="📥")
                    next_step()
                    st.rerun()
                else:
                    st.warning("Please upload a file first, or switch to Camera Capture.")

        with col_skip:
            if st.button("⏭ Skip this document", key=f"skip_upload_{st.session_state.step}"):
                next_step()
                st.rerun()

    # ── TAB 2: Camera Capture ──────────────────────────────────────────────
    with tab_camera:
        st.markdown(
            '<div class="cam-instruction">'
            '📷 <b>Fast Capture:</b> Point your camera at the document and click <b>Take Photo</b>. '
            'The image will be stored instantly into your database folder and queued for fast parallel processing at the end.'
            '</div>',
            unsafe_allow_html=True,
        )

        camera_img = st.camera_input(
            f"Capture {current_doc_type}",
            key=f"cam_{st.session_state.step}",
        )

        if camera_img is not None:
            pil_img = Image.open(io.BytesIO(camera_img.getvalue())).convert("RGB")
            st.image(pil_img, caption="Captured photo preview", use_container_width=True)

        col_confirm_cam, col_skip_cam = st.columns([3, 7])
        with col_confirm_cam:
            if st.button("✅ Confirm & Next", type="primary", key=f"confirm_cam_{st.session_state.step}"):
                if camera_img is not None:
                    saved_path = None
                    db_folder = st.session_state.camera_db_folder
                    if db_folder:
                        try:
                            saved_path = save_image_to_db(pil_img, current_doc_type, db_folder)
                            st.toast(f"📁 Image saved: {os.path.basename(saved_path)}", icon="💾")
                        except Exception as e:
                            st.warning(f"Could not save image: {e}")

                    st.session_state.pending_items.append({
                        "type": current_doc_type,
                        "input_type": "camera",
                        "pil_img": pil_img,
                        "saved_path": saved_path,
                    })
                    next_step()
                    st.rerun()
                else:
                    st.warning("Please take a photo first.")

        with col_skip_cam:
            if st.button("⏭ Skip this document", key=f"skip_cam_{st.session_state.step}"):
                next_step()
                st.rerun()

else:
    # ── Final Processing & Results Page ───────────────────────────────────────
    st.header("📋 Inspection Results")

    col_r, col_s = st.columns([2, 8])
    with col_r:
        if st.button("🔄 Start Over"):
            reset()
            st.rerun()

    # ── Run Parallel OCR Processing if pending ────────────────────────────────
    if st.session_state.pending_items:
        n_items = len(st.session_state.pending_items)
        with st.status(f"🚀 Running Adaptive OCR (PaddleOCR + Tesseract) on {n_items} document(s)...", expanded=True) as status:
            processed_results = [None] * n_items
            
            # Execute OCR in parallel threads
            max_workers = min(4, n_items)
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                future_to_idx = {
                    executor.submit(process_single_item, item): idx
                    for idx, item in enumerate(st.session_state.pending_items)
                }
                
                for future in as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    try:
                        res = future.result()
                        processed_results[idx] = res
                        doc_name = res["type"]
                        n_lines = len(res["elements"])
                        engine_label, _ = _ENGINE_LABELS.get(res.get("engine", "paddle_only"), ("🟢 PaddleOCR", "#00c853"))
                        st.write(f"✅ **{doc_name}** — {n_lines} text elements extracted via {engine_label} (confidence: {res['confidence']:.1%})")
                    except Exception as e:
                        st.write(f"❌ Error processing document #{idx+1}: {e}")

            # Collect non-None results
            for r in processed_results:
                if r is not None:
                    st.session_state.docs.append(r)
            
            # Clear pending queue
            st.session_state.pending_items = []
            status.update(label="🎉 All OCR processing completed (adaptive dual-engine)!", state="complete", expanded=False)

    if not st.session_state.docs:
        st.error("No documents were uploaded or captured.")
        st.stop()

    po_doc = next((d for d in st.session_state.docs if d["type"] == "Purchase Order"), None)

    # ── Captured image database summary ──────────────────────────────────────
    camera_docs = [d for d in st.session_state.docs if d.get("source") == "camera"]
    if camera_docs and st.session_state.camera_db_folder:
        st.success(
            f"📷 **{len(camera_docs)} camera image(s)** saved to local database: `{st.session_state.camera_db_folder}`"
        )
        saved_files = [d.get("saved_path") for d in camera_docs if d.get("saved_path")]
        if saved_files:
            with st.expander("🗂️ View saved image database files"):
                for p in saved_files:
                    st.markdown(f"- `{p}`")

    # ── 1. Raw OCR text dump ───────────────────────────────────────────────────
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

    # ── Show OCR text & Bounding Box preview per doc ──────────────────────────
    st.markdown("#### 🔍 OCR Text & Image Analysis (Per Document)")
    for doc in st.session_state.docs:
        source_badge = "📷 Camera" if doc.get("source") == "camera" else "📂 Upload"
        engine_key = doc.get("engine", "paddle_only")
        engine_label, engine_color = _ENGINE_LABELS.get(engine_key, ("🟢 PaddleOCR", "#00c853"))
        with st.expander(
            f"{source_badge} | 📄 {doc['type']} — {len(doc['elements'])} lines "
            f"(confidence: {doc['confidence']:.1%}) | {engine_label}"
        ):
            metric_a, metric_b, metric_c, metric_d = st.columns(4)
            metric_a.metric("Text elements", len(doc["elements"]))
            metric_b.metric("OCR confidence", f"{doc['confidence']:.1%}")
            metric_c.metric("Pages / Images", len(doc["images"]))
            metric_d.metric("OCR engine", engine_label)

            # Show engine breakdown if multiple pages used different engines
            engine_counts = doc.get("engine_counts", {})
            if len(engine_counts) > 1:
                breakdown = ", ".join(
                    f"{_ENGINE_LABELS.get(e, (e, ''))[0]}: {c} page(s)"
                    for e, c in engine_counts.items()
                )
                st.info(f"🔀 **Adaptive OCR per-page breakdown:** {breakdown}")
            elif engine_key == "tesseract":
                st.info("🔵 **Tesseract was used** — PaddleOCR confidence was below threshold on this document.")
            elif engine_key == "paddle":
                st.success("🟢 **PaddleOCR** delivered high-confidence results — no fallback needed.")
            else:
                st.info("🟢 **PaddleOCR** — Tesseract not installed; running in Paddle-only mode.")

            if doc.get("saved_path"):
                st.markdown(f"💾 Saved to database: `{doc['saved_path']}`")

            # Draw bounding boxes on photo/image
            if doc["images"]:
                boxes = [
                    el["box"] for el in doc["elements"]
                    if el.get("box") is not None and len(el["box"]) > 0
                ]
                if boxes:
                    annotated = draw_ocr_boxes(doc["images"][0], boxes)
                    st.image(annotated, caption=f"{engine_label} Bounding Boxes — {doc['type']}", use_container_width=True)
                else:
                    st.image(doc["images"][0], caption=f"Captured Image — {doc['type']}", use_container_width=True)

            if doc["elements"]:
                st.code(doc["raw_text"], language=None)
            else:
                st.error("OCR returned no text for this document. Verify readable content.")

            extracted = {
                field.replace("_", " ").title(): value
                for field, value in doc["extraction"].model_dump().items()
                if value not in (None, "")
            }
            st.markdown("**Extracted document details**")
            if extracted:
                st.json(extracted)
            else:
                st.warning("No labeled fields were found. Raw OCR text is used for comparison.")

    # ── 2. Cross-reference (requires PO + supporting docs) ───────────────────
    if po_doc:
        supporting_docs = [d for d in st.session_state.docs if d["type"] != "Purchase Order"]
        if supporting_docs:
            st.markdown("### 🔍 Cross-Reference Verification (PO vs Documents)")
            for supp_doc in supporting_docs:
                source_badge = "📷" if supp_doc.get("source") == "camera" else "📂"
                st.subheader(f"{source_badge} PO vs {supp_doc['type']}")
                results = compare_documents(po_doc["extraction"], supp_doc["extraction"])
                for field, data in results.items():
                    status = data["status"]
                    icon = "✅" if status == "match" else "❌" if "mismatch" in status else "⚠️"
                    st.markdown(
                        f"**{field.replace('_', ' ').title()}**: {icon} {data['detail']} "
                        f"(PO: *{data['base'] or 'Not found'}* | Doc: *{data['supporting'] or 'Not found'}*)"
                    )

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
