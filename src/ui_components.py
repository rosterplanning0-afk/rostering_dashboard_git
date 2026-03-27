import streamlit as st
import json
import os
import datetime

def render_sidebar():
    st.sidebar.markdown("### :material/settings: Dashboard Controls")
    
    # Load dynamic config
    config_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.json')
    with open(config_path, 'r') as f:
        config = json.load(f)

    st.sidebar.markdown("---")
    st.sidebar.markdown("#### :material/calendar_month: Select Time Period")
    
    if 'selected_date' not in st.session_state:
        st.session_state['selected_date'] = datetime.datetime.now().date()
        
    current_date = st.session_state['selected_date']
    selected_date = st.sidebar.date_input("Date", value=current_date)
    
    if selected_date != current_date:
        st.session_state['selected_date'] = selected_date
        st.rerun()

    st.sidebar.markdown("#### :material/business: Select Department")
    dept_options = list(config['departments'].keys())
    
    # Init state
    if 'selected_dept' not in st.session_state:
        st.session_state['selected_dept'] = 'All'
    if 'selected_role' not in st.session_state:
        st.session_state['selected_role'] = 'All'
        
    current_dept = st.session_state['selected_dept']
    current_role = st.session_state['selected_role']
    
    dept_idx = 0 if current_dept == 'All' else (dept_options.index(current_dept) + 1 if current_dept in dept_options else 0)
    
    selected_dept = st.sidebar.selectbox(
        "Choose Department", 
        ["All"] + dept_options, 
        index=dept_idx, 
        help="Select the department to filter data"
    )
    
    role_options = ["All"]
    if selected_dept != "All":
        roles_dict = config['departments'][selected_dept]
        role_options = ["All"] + list(roles_dict.values())
        
    # If the department changed, we must urgently reset the role and trigger a rerun
    if selected_dept != current_dept:
        st.session_state['selected_dept'] = selected_dept
        st.session_state['selected_role'] = 'All'
        st.rerun()
        
    role_idx = 0 if current_role == 'All' or current_role not in role_options else role_options.index(current_role)
    
    selected_role = st.sidebar.selectbox(
        "Choose Designation", 
        role_options, 
        index=role_idx, 
        help="Filter data by role"
    )
    
    # State update and rerun for role change
    if selected_role != current_role:
        st.session_state['selected_role'] = selected_role
        st.rerun()
    
    st.sidebar.markdown("---")
    st.sidebar.markdown("### :material/admin_panel_settings: Admin Actions")
    
    force_sync = st.sidebar.checkbox("Bypass 8-Hour Sync Filter", value=False, help="Forces a full resync of all rosters in the Drive directory regardless of modification date")
    
    if st.sidebar.button(":material/sync: Sync New Rosters"):
        with st.spinner("Fetching from Drive..."):
            from src.processor import process_new_rosters
            result = process_new_rosters(force_all=force_sync)
            if result and result.get("status") == "success":
                st.sidebar.success(result.get("message"))
            else:
                st.sidebar.error(result.get("message", "Unknown error occurred."))
                
    return config
