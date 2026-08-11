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

st.set_page_config(page_title="Incoming Goods Inspection & Store Receiving", layout="wide", page_icon="🏭")

# ─── Module imports ───────────────────────────────────────────────────────────
import config
from utils import pdf_to_images, draw_ocr_boxes
from ocr import perform_ocr
from extractor import extract_fields
from comparison import compare_documents
from report import export_excel, export_raw_text_excel
from bin_master import determine_bin_location
from epicor_receipt import generate_epicor_dmt_receipt_csv, save_to_epicor_network_share
from scanner_watcher import start_scanner_folder_watcher

# ─── Custom Styling ───────────────────────────────────────────────────────────
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
    .bin-card {
        background: linear-gradient(135deg, #1e293b 0%, #0f172a 100%);
        border: 2px solid #38bdf8;
        border-radius: 12px;
        padding: 1.2rem;
        color: white;
        margin: 1rem 0;
    }
    .bin-quarantine {
        background: linear-gradient(135deg, #450a0a 0%, #7f1d1d 100%);
        border: 2px solid #ef4444;
        border-radius: 12px;
        padding: 1.2rem;
        color: white;
        margin: 1rem 0;
    }
</style>
""", unsafe_allow_html=True)

# ─── Processing version guard & session init ──────────────────────────────────
PROCESSING_VERSION = 6
if st.session_state.get("processing_version") != PROCESSING_VERSION:
    st.session_state.processing_version = PROCESSING_VERSION
    st.session_state.step = 0
    st.session_state.docs = []
    st.session_state.pending_items = []
    st.session_state.camera_db_folder = r"C:\Users\shailesh\Documents\InspectionImages"
    st.session_state.scanner_inbox = r"C:\ScanInbox"

if "step" not in st.session_state:
    st.session_state.step = 0
if "docs" not in st.session_state:
    st.session_state.docs = []
if "pending_items" not in st.session_state:
    st.session_state.pending_items = []
if "camera_db_folder" not in st.session_state:
    st.session_state.camera_db_folder = r"C:\Users\shailesh\Documents\InspectionImages"
if "scanner_inbox" not in st.session_state:
    st.session_state.scanner_inbox = r"C:\Users\shailesh\Documents\ScanInbox"


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
    primary_engine = max(engine_counts, key=engine_counts.get) if engine_counts else "paddle_only"
    extraction = extract_fields(all_text)

    return {
        "type":          doc_type,
        "images":        images,
        "raw_text":      all_text,
        "elements":      all_elements,
        "confidence":    overall_conf,
        "extraction":    extraction,
        "engine":        primary_engine,
        "engine_counts": engine_counts,
    }


def process_single_item(item):
    """Processes a pending document (file, camera, or scanner) through OCR."""
    doc_type = item["type"]
    input_type = item["input_type"]

    if input_type in ["file", "scanner"]:
        file_obj_or_path = item["file"]
        
        if isinstance(file_obj_or_path, str):
            # Scanner file path
            tmp_path = file_obj_or_path
            ext = os.path.splitext(tmp_path)[1].lower()
            cleanup_tmp = False
        else:
            # Uploaded File object
            uploaded_file = file_obj_or_path
            ext = os.path.splitext(uploaded_file.name)[1].lower()
            with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                tmp.write(uploaded_file.read())
                tmp_path = tmp.name
            cleanup_tmp = True

        try:
            if ext == ".pdf":
                images = pdf_to_images(tmp_path, dpi=config.PDF_DPI)
            else:
                with Image.open(tmp_path) as img:
                    images = [img.copy().convert("RGB")]
        finally:
            if cleanup_tmp:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

        res = _run_ocr_and_extract(images, doc_type)
        res["source"] = input_type
        res["saved_path"] = item.get("saved_path") or (tmp_path if not cleanup_tmp else None)
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
st.title("🏭 Aerospace Store Receiving & EPICOR ERP Entry System")
st.markdown("Automated Document Verification, OCR Comparison, EPICOR GRN Receipt Creation, and Shop Floor BIN Assignment.")

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

    # ── Configuration Panel on Step 1 (Purchase Order) ───────────────────────
    if st.session_state.step == 0:
        col_c1, col_c2 = st.columns(2)
        with col_c1:
            st.markdown("### 📁 Local Database Folder")
            folder_input = st.text_input(
                "Folder Path for Image Database",
                value=st.session_state.camera_db_folder,
                placeholder=r"e.g. C:\Users\shailesh\Documents\InspectionImages",
                key="po_folder_input",
            )
            if folder_input.strip():
                st.session_state.camera_db_folder = folder_input.strip()

        with col_c2:
            st.markdown("### 🖨️ Ricoh fi-8170 Scanner Inbox")
            scanner_input = st.text_input(
                "Scanner Hot Folder Path",
                value=st.session_state.scanner_inbox,
                placeholder=r"e.g. C:\Users\shailesh\Documents\ScanInbox",
                key="scanner_folder_input",
            )
            if scanner_input.strip():
                st.session_state.scanner_inbox = scanner_input.strip()
                try:
                    os.makedirs(st.session_state.scanner_inbox, exist_ok=True)
                except Exception as e:
                    st.warning(f"Note: Unable to create folder `{st.session_state.scanner_inbox}` ({e})")
                
        st.divider()

    # ── Input mode tabs ────────────────────────────────────────────────────
    tab_upload, tab_camera, tab_scanner = st.tabs(["📂 Upload File", "📷 Camera Capture", "🖨️ Ricoh fi-8170 Scanner"])

    # ── TAB 1: File Upload ─────────────────────────────────────────────────
    with tab_upload:
        uploaded_file = st.file_uploader(
            f"Upload {current_doc_type} (PDF / PNG / JPG)",
            type=["pdf", "png", "jpg", "jpeg", "tif", "tiff"],
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
                    st.warning("Please upload a file first, or switch tab.")

        with col_skip:
            if st.button("⏭ Skip this document", key=f"skip_upload_{st.session_state.step}"):
                next_step()
                st.rerun()

    # ── TAB 2: Camera Capture ──────────────────────────────────────────────
    with tab_camera:
        st.markdown(
            '<div class="cam-instruction">'
            '📷 <b>Fast Capture:</b> Point camera at document and click <b>Take Photo</b>. '
            'Stored instantly into local database folder and queued for processing.'
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

    # ── TAB 3: Ricoh fi-8170 Scanner Inbox ─────────────────────────────────
    with tab_scanner:
        inbox_folder = st.session_state.scanner_inbox
        st.markdown(
            f'<div class="cam-instruction">'
            f'🖨️ <b>Ricoh fi-8170 Integration:</b> Feed high-res printed documents into scanner.<br>'
            f'Auto-monitoring inbox folder: <code>{inbox_folder}</code>'
            f'</div>',
            unsafe_allow_html=True,
        )
        
        inbox_files = []
        if os.path.exists(inbox_folder):
            inbox_files = [
                os.path.join(inbox_folder, f) for f in os.listdir(inbox_folder)
                if os.path.splitext(f)[1].lower() in [".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"]
            ]
            
        if inbox_files:
            selected_scan = st.selectbox(
                f"Select scanned file for {current_doc_type}",
                options=inbox_files,
                format_func=os.path.basename,
                key=f"scan_select_{st.session_state.step}"
            )
            
            if st.button("✅ Ingest Scanned Document", type="primary", key=f"confirm_scan_{st.session_state.step}"):
                st.session_state.pending_items.append({
                    "type": current_doc_type,
                    "input_type": "scanner",
                    "file": selected_scan,
                    "saved_path": selected_scan
                })
                st.toast(f"🖨️ Ingested scan: {os.path.basename(selected_scan)}", icon="📥")
                next_step()
                st.rerun()
        else:
            st.info(f"Scanning folder `{inbox_folder}` is currently empty. Drop scanned files here or use Ricoh PaperStream scanner.")
            if st.button("⏭ Skip this document", key=f"skip_scanner_{st.session_state.step}"):
                next_step()
                st.rerun()

else:
    # ── Final Processing, Verification & Store Receiving Results Page ──────────
    st.header("📋 Aerospace Store Receiving Results")

    col_r, col_s = st.columns([2, 8])
    with col_r:
        if st.button("🔄 Start New Receiving Batch"):
            reset()
            st.rerun()

    # ── Run Parallel OCR Processing if pending ────────────────────────────────
    if st.session_state.pending_items:
        n_items = len(st.session_state.pending_items)
        with st.status(f"🚀 Running Adaptive Dual-Engine OCR (PaddleOCR + Tesseract) on {n_items} document(s)...", expanded=True) as status:
            processed_results = [None] * n_items
            
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

            for r in processed_results:
                if r is not None:
                    st.session_state.docs.append(r)
            
            st.session_state.pending_items = []
            status.update(label="🎉 All OCR processing completed (adaptive dual-engine)!", state="complete", expanded=False)

    if not st.session_state.docs:
        st.error("No documents were uploaded or captured.")
        st.stop()

    po_doc = next((d for d in st.session_state.docs if d["type"] == "Purchase Order"), None)
    po_number = po_doc["extraction"].po_number if po_doc else "12345"

    # ── 1. Document Comparison & High-Precision Match Analysis ───────────────
    st.markdown("### 🔍 High-Precision Document Matching & Word-for-Word Analysis")
    
    is_overall_approved = True
    overall_match_pcts = []
    
    if po_doc:
        supporting_docs = [d for d in st.session_state.docs if d["type"] != "Purchase Order"]
        if supporting_docs:
            for supp_doc in supporting_docs:
                st.subheader(f"📄 PO vs {supp_doc['type']}")
                results = compare_documents(po_doc["extraction"], supp_doc["extraction"])
                summary = results.pop("_summary", {})
                
                match_pct = summary.get("overall_match_pct", 0.0)
                overall_match_pcts.append(match_pct)
                approved = summary.get("is_approved", False)
                if not approved:
                    is_overall_approved = False

                col_m1, col_m2 = st.columns(2)
                col_m1.metric("Similarity Matching Confidence", f"{match_pct:.1f}%")
                col_m2.metric("Compliance Status", "✅ APPROVED" if approved else "❌ REJECTED")

                # Field details
                for field, data in results.items():
                    status_flag = data["status"]
                    icon = "✅" if status_flag == "match" else "⚠️" if "partial" in status_flag else "❌"
                    st.markdown(
                        f"**{field.replace('_', ' ').title()}**: {icon} {data['detail']} "
                        f"(PO: *{data['base'] or 'Not found'}* | Doc: *{data['supporting'] or 'Not found'}*)"
                    )
    else:
        st.warning("Purchase Order document was skipped. Cross-reference comparison requires PO.")

    st.divider()

    # ── 2. Shop Floor Worker BIN Assignment Card ──────────────────────────────
    st.markdown("### 📦 Shop Floor Worker BIN Location Recommendation")
    
    sample_ext = po_doc["extraction"].model_dump() if po_doc else {}
    bin_info = determine_bin_location(sample_ext, is_approved=is_overall_approved)
    
    if bin_info["status"] == "APPROVED":
        st.markdown(
            f'<div class="bin-card">'
            f'<h2>✅ APPROVED RECEIVING — MOVE TO BIN</h2>'
            f'<h3>📍 Assigned BIN Location: <code>{bin_info["bin"]}</code></h3>'
            f'<p><b>Warehouse Zone:</b> {bin_info["zone"]}<br>'
            f'<b>Rack / Drawer:</b> {bin_info["rack"]}<br>'
            f'<b>Instruction:</b> {bin_info["instruction"]}</p>'
            f'</div>',
            unsafe_allow_html=True
        )
    else:
        st.markdown(
            f'<div class="bin-quarantine">'
            f'<h2>⚠️ QUARANTINE / INSPECTION HOLD</h2>'
            f'<h3>📍 Target Bin: <code>{bin_info["bin"]}</code></h3>'
            f'<p><b>Zone:</b> {bin_info["zone"]}<br>'
            f'<b>Reason:</b> {bin_info["reason"]}<br>'
            f'<b>Action Required:</b> {bin_info["instruction"]}</p>'
            f'</div>',
            unsafe_allow_html=True
        )

    st.divider()

    # ── 3. EPICOR ERP Receipt Entry & DMT CSV Exporter ─────────────────────────
    st.markdown("### ⚡ EPICOR ERP On-Premise Integration & Goods Receipt (GRN)")
    
    col_e1, col_e2 = st.columns(2)
    
    with col_e1:
        st.markdown("#### 1. EPICOR Shared Network Folder Upload")
        share_folder = st.text_input("EPICOR Network Share Path", value=r"C:\Users\shailesh\Desktop\Ujjval\01-Automation\99-\reports\epicor_attachments")
        if st.button("📁 Stream Attachments to EPICOR Share"):
            saved_paths = []
            for d in st.session_state.docs:
                p = save_to_epicor_network_share(d["images"], po_number, d["type"], share_folder)
                saved_paths.append(p)
            st.success(f"✅ Saved {len(saved_paths)} document evidence file(s) to EPICOR share path!")
            for p in saved_paths:
                st.markdown(f"- `{p}`")

    with col_e2:
        st.markdown("#### 2. EPICOR Receipt Entry (DMT CSV Exporter)")
        report_dir = os.path.join(os.path.dirname(__file__), "reports")
        dmt_csv_path = os.path.join(report_dir, f"epicor_dmt_receipt_PO_{po_number}.csv")
        
        generate_epicor_dmt_receipt_csv(st.session_state.docs, po_number, dmt_csv_path)
        
        with open(dmt_csv_path, "rb") as f:
            st.download_button(
                "📦 Download EPICOR Receipt DMT CSV",
                f,
                file_name=os.path.basename(dmt_csv_path),
                type="primary",
            )
        st.caption("Import this CSV directly into EPICOR Data Migration Tool (DMT) for 1-click Receipt Entry creation.")

    st.divider()

    # ── 4. Raw OCR Text & Image Bounding Boxes Inspection ──────────────────────
    st.markdown("### 📥 Raw OCR Data & Visual Bounding Box Analysis")
    for doc in st.session_state.docs:
        source_badge = "🖨️ Scanner" if doc.get("source") == "scanner" else ("📷 Camera" if doc.get("source") == "camera" else "📂 Upload")
        engine_key = doc.get("engine", "paddle_only")
        engine_label, _ = _ENGINE_LABELS.get(engine_key, ("🟢 PaddleOCR", "#00c853"))
        with st.expander(
            f"{source_badge} | 📄 {doc['type']} — {len(doc['elements'])} lines "
            f"(confidence: {doc['confidence']:.1%}) | {engine_label}"
        ):
            if doc["images"]:
                boxes = [
                    el["box"] for el in doc["elements"]
                    if el.get("box") is not None and len(el["box"]) > 0
                ]
                if boxes:
                    annotated = draw_ocr_boxes(doc["images"][0], boxes)
                    st.image(annotated, caption=f"{engine_label} Bounding Boxes — {doc['type']}", use_container_width=True)
            st.code(doc["raw_text"], language=None)
