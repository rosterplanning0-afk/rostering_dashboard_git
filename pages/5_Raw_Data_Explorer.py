import streamlit as st
import pandas as pd
from src.supabase_client import get_supabase_client
from src.reconciliation import (
    filter_active_employees,
    filter_roster_scope,
    get_roster_not_in_active,
    load_employee_master,
)
from src.ui_components import render_sidebar
from datetime import datetime

# Render Global Sidebar and get config
config = render_sidebar()
selected_date = st.session_state.get('selected_date', datetime.now().date())

st.title(f":material/folder_open: Raw Data Explorer - {selected_date}")

@st.cache_data(ttl=60)
def load_page_data(date_str):
    client = get_supabase_client()

    # We join raw_roster_data and processed_roster on emp_id and date
    res_raw = client.table('raw_roster_data').select('name, emp_id, duty_code_raw, shift_start, shift_end, crew_type').eq('date', date_str).execute()
    res_processed = client.table('processed_roster').select('emp_id, duty_category, status').eq('date', date_str).execute()
    emp_df = load_employee_master(client)

    if res_raw.data and res_processed.data:
        df_raw = pd.DataFrame(res_raw.data)
        df_proc = pd.DataFrame(res_processed.data)

        # Merge on Employee ID
        merged_df = pd.merge(df_raw, df_proc, on='emp_id', how='left')
        return merged_df, emp_df

    return pd.DataFrame(), emp_df

with st.spinner("Executing detailed join..."):
    df, emp_df = load_page_data(str(selected_date))

selected_dept = st.session_state.get('selected_dept', 'All')
selected_role = st.session_state.get('selected_role', 'All')

df = filter_roster_scope(df, config, selected_dept, selected_role)
active_emp_df = filter_active_employees(emp_df, selected_dept, selected_role)
roster_gap_df = get_roster_not_in_active(df, active_emp_df)

if not df.empty:
    st.markdown("### Staff Reconciliation Exceptions")
    if roster_gap_df.empty:
        st.success("All rostered staff in the current filter scope exist in the active employee master.")
    else:
        st.warning(
            f"{len(roster_gap_df)} rostered staff are missing from the active employee master for the current filters."
        )
        st.dataframe(roster_gap_df, width='stretch', hide_index=True)

    st.markdown("### Full Data Explorer")

    # Basic Filtering
    c1, c2 = st.columns(2)
    with c1:
        category_filter = st.selectbox("Filter by Category", ['All'] + list(df['duty_category'].unique()))
    with c2:
        status_filter = st.selectbox("Filter by Status", ['All'] + list(df['status'].unique()))
        
    filtered_df = df.copy()
    if category_filter != 'All':
        filtered_df = filtered_df[filtered_df['duty_category'] == category_filter]
    if status_filter != 'All':
        filtered_df = filtered_df[filtered_df['status'] == status_filter]
        
    st.dataframe(filtered_df, width='stretch', hide_index=True)
    
    # Download Button
    csv = filtered_df.to_csv(index=False).encode('utf-8')
    st.download_button(
        label=":material/download: Download Data as CSV",
        data=csv,
        file_name=f"roster_data_{selected_date}.csv",
        mime='text/csv',
    )
    
else:
    st.info(f"No detailed records found for {selected_date} under the current filters.")
