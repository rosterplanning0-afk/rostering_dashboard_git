import os
from datetime import datetime

import streamlit as st
from dotenv import load_dotenv

from src.drive_api import get_drive_upload_service, get_or_create_folder, upload_pdf_to_drive, get_google_drive_folder_id
from src.processor import process_new_rosters
from src.ui_components import render_sidebar

load_dotenv()

config = render_sidebar()

FOLDER_ID = get_google_drive_folder_id()
departments = config.get('departments', {})
current_year = str(datetime.now().year)

st.title(":material/upload_file: Upload Roster PDF")
st.markdown(
    "Select a **Department** and **Designation**, then upload a PDF roster file to Google Drive. "
    "The roster is automatically synced after a successful upload."
)
st.markdown("---")

# ── Step 1: Department / Designation ────────────────────────────────────────
st.markdown("### Step 1 — Select Department & Designation")

col1, col2 = st.columns(2)

with col1:
    dept_options = list(departments.keys())
    dept_choice = st.selectbox(
        "Department *",
        options=["— select —"] + dept_options,
        key="upload_dept_select",
    )

with col2:
    desig_options = (
        list(departments[dept_choice].values())
        if dept_choice != "— select —"
        else []
    )
    desig_choice = st.selectbox(
        "Designation *",
        options=["— select —"] + desig_options,
        key="upload_desig_select",
        disabled=(dept_choice == "— select —"),
    )

both_selected = (dept_choice != "— select —") and (desig_choice != "— select —")

# ── Step 2: File upload ───────────────────────────────────────────────────────
st.markdown("### Step 2 — Upload PDF File")

if not both_selected:
    st.info("Please select both **Department** and **Designation** above to enable the file uploader.")
else:
    target_path = f"My Drive  /  roster  /  {dept_choice}  /  {current_year}"
    st.caption(f":material/folder: Target Drive path: **{target_path}**")

uploaded_file = st.file_uploader(
    "Choose a PDF roster file",
    type=["pdf"],
    disabled=not both_selected,
    help="Only PDF files are accepted. A file with the same name in the target folder will be replaced.",
    key="upload_file_input",
)

if uploaded_file is not None and both_selected:
    file_size_kb = len(uploaded_file.getvalue()) / 1024
    st.success(f":material/description: **{uploaded_file.name}** ready ({file_size_kb:.1f} KB)")

    st.markdown("---")
    if st.button(
        ":material/cloud_upload: Upload & Sync",
        type="primary",
        width='content',
    ):
        if not FOLDER_ID or FOLDER_ID == "your-folder-id":
            st.error(
                "**GOOGLE_DRIVE_FOLDER_ID** is not configured. "
                "Please set it in your `.env` file and restart the app."
            )
            st.stop()

        # ── Upload phase ─────────────────────────────────────────────────────
        upload_ok = False
        replaced = False

        with st.status(
            f"Uploading **{uploaded_file.name}** to Google Drive…", expanded=True
        ) as upload_status:
            try:
                st.write("🔌 Connecting to Google Drive…")
                service = get_drive_upload_service()

                st.write(f"📂 Navigating to `roster / {dept_choice} / {current_year}`…")
                dept_folder_id = get_or_create_folder(service, FOLDER_ID, dept_choice)
                year_folder_id = get_or_create_folder(service, dept_folder_id, current_year)

                st.write(f"⬆️ Uploading **{uploaded_file.name}**…")
                file_bytes = uploaded_file.getvalue()
                file_id, replaced = upload_pdf_to_drive(
                    service, file_bytes, uploaded_file.name, year_folder_id
                )

                action_label = "replaced" if replaced else "uploaded"
                upload_status.update(
                    label=f"✅ **{uploaded_file.name}** successfully {action_label}.",
                    state="complete",
                )
                st.write(f"Drive file ID: `{file_id}`")
                upload_ok = True

            except Exception as exc:
                upload_status.update(label="❌ Upload failed.", state="error")
                st.error(f"Upload error: {exc}")

        # ── Auto-sync phase ──────────────────────────────────────────────────
        if upload_ok:
            with st.status("Syncing all rosters from Google Drive…", expanded=True) as sync_status:
                try:
                    st.write("🔄 Running roster sync pipeline…")
                    result = process_new_rosters(force_all=False)
                    msg = (result or {}).get("message", "Sync finished.")
                    status_code = (result or {}).get("status", "info")

                    if status_code == "success":
                        sync_status.update(label="✅ Sync complete.", state="complete")
                        st.success(msg)
                    else:
                        sync_status.update(label="ℹ️ Sync finished.", state="complete")
                        st.info(msg)

                except Exception as exc:
                    sync_status.update(label="⚠️ Sync warning.", state="error")
                    st.warning(
                        f"The file was uploaded successfully, but the auto-sync encountered "
                        f"an error: {exc}"
                    )
