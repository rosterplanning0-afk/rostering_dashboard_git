import streamlit as st
import pandas as pd
import datetime
from src.supabase_client import get_supabase_client
from src.ui_components import render_sidebar

st.markdown("## :material/person: Employee Profile & HR Competency Management")
st.markdown("Manage time-bounded roles and historical designations (e.g. Train Operator vs Crew Controller) per individual operator.")

# Initialize standard sidebar config
config = render_sidebar()
client = get_supabase_client()

@st.cache_data(ttl=60)
def load_employees():
    """Load employees using filters to comply with RLS policies."""
    all_emps = []
    for status_val in ['Active', 'Inactive']:
        try:
            res = client.table("employees").select(
                "employee_id, name, designation, department, status, gender, date_joined"
            ).eq("status", status_val).execute()
            if res.data:
                all_emps.extend(res.data)
        except Exception as e:
            st.warning(f"Could not load {status_val} employees: {e}")
    return pd.DataFrame(all_emps) if all_emps else pd.DataFrame()

@st.cache_data(ttl=5)
def load_competencies(emp_id):
    try:
        res = client.table("employee_competencies").select("*").eq("employee_id", emp_id).order("valid_from", desc=True).execute()
        return pd.DataFrame(res.data) if res.data else pd.DataFrame()
    except Exception as e:
        return pd.DataFrame()

emp_df = load_employees()

if emp_df.empty:
    st.warning("No employees found in database. Please check your Supabase connection and RLS policies.")
    st.stop()

# Build dropdown - show active employees first, then inactive
if 'status' in emp_df.columns:
    emp_df = emp_df.sort_values(['status', 'name'], ascending=[True, True])  # Active sorts before Inactive
emp_options = {f"{row['employee_id']} - {row['name']} ({row.get('designation','N/A')})": str(row['employee_id']) for _, row in emp_df.iterrows()}

st.markdown("### Search Employee")
selected_label = st.selectbox("Select Employee by ID or Name", list(emp_options.keys()))
selected_emp_id = emp_options[selected_label]

st.divider()

col1, col2 = st.columns([1, 1])

# Fetch live competencies
comp_df = load_competencies(selected_emp_id)

with col1:
    st.markdown("### Active & Historical Competencies")
    if comp_df.empty:
        st.info("No explicit historical competencies recorded for this employee yet.")
    else:
        # Format for UI
        display_df = comp_df[['department', 'designation', 'valid_from', 'valid_till', 'is_active', 'created_at']].copy()
        
        # Apply strict data-dense styling
        st.dataframe(
            display_df,
            hide_index=True,
            width='stretch',
            column_config={
                "department": "Department",
                "designation": "Designation / Role",
                "valid_from": st.column_config.DateColumn("Valid From", format="YYYY-MM-DD"),
                "valid_till": st.column_config.DateColumn("Valid Till", format="YYYY-MM-DD"),
                "is_active": "Currently Active",
                "created_at": "Logged On"
            }
        )
        
with col2:
    st.markdown("### :material/add_circle: Append New Role")
    st.markdown("Assign a new competency mapping for this employee.")
    
    with st.form("add_comp_form", clear_on_submit=True):
        f_dept = st.text_input("Department", value="Train Operations")
        f_desig = st.selectbox("Designation", ["Train Operator", "Crew Controller", "Train Attendant", "Station Controller", "Depot Controller"])
        
        c1, c2 = st.columns(2)
        f_from = c1.date_input("Valid From Date")
        f_till = c2.date_input("Valid Till Date (Optional)", value=None)
        
        f_active = st.checkbox("Set as Currently Active Role", value=True)
        
        submitted = st.form_submit_button("Save Competency Record", type="primary")
        if submitted:
            payload = {
                "employee_id": selected_emp_id,
                "department": f_dept,
                "designation": f_desig,
                "valid_from": f_from.isoformat() if f_from else None,
                "valid_till": f_till.isoformat() if f_till else None,
                "is_active": f_active
            }
            try:
                client.table("employee_competencies").insert(payload).execute()
                st.success(f"Successfully recorded `{f_desig}` competency for {selected_emp_id}!")
                load_competencies.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Failed to record competency constraints: {e}")
