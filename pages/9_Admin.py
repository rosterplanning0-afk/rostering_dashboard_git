import streamlit as st
from src.processor import process_new_rosters
from src.ui_components import render_sidebar

config = render_sidebar()

st.title(":material/admin_panel_settings: Administration")
st.markdown("---")
st.markdown("### :material/sync: Roster Synchronization")

force_sync = st.checkbox(
    "Bypass 8-Hour Sync Filter", 
    value=False, 
    help="Forces a full resync of all rosters in the Drive directory regardless of modification date."
)

if st.button(":material/sync: Sync New Rosters", type="primary"):
    with st.spinner("Fetching from Drive..."):
        result = process_new_rosters(force_all=force_sync)
        if result and result.get("status") == "success":
            st.success(result.get("message"))
        else:
            st.error(result.get("message", "Unknown error occurred."))

