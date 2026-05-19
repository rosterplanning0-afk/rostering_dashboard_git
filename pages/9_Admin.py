import streamlit as st
import pandas as pd
import datetime
import json
from src.processor import process_new_rosters
from src.ui_components import render_sidebar
from src.supabase_client import get_supabase_client

config = render_sidebar()
client = get_supabase_client()

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

st.markdown("---")
st.markdown("### :material/settings: Update Required Counts")
st.markdown("Configure historical required counts for each role. Changes apply from the selected Effective Date onwards.")

roles = config.get("roles", [])
if not roles:
    for dept_roles in config.get("departments", {}).values():
        roles.extend(list(dept_roles.values()))
roles = sorted(list(set(roles)))

selected_role = st.selectbox("Select Role to Update", roles)
effective_date = st.date_input("Effective Date", value=datetime.date.today())

# Fetch existing values
existing_plan_res = client.table('role_required_counts')\
    .select('*')\
    .eq('role', selected_role)\
    .lte('effective_date', str(effective_date))\
    .order('effective_date', desc=True)\
    .limit(1)\
    .execute()

existing_plan = {}
if existing_plan_res.data:
    existing_plan = existing_plan_res.data[0]

with st.form("update_counts_form"):
    st.write(f"Editing counts for **{selected_role}** effective **{effective_date}**")
    
    col1, col2 = st.columns(2)
    with col1:
        total_shift_duty = st.number_input("Total Shift Duty Required", value=int(existing_plan.get('total_shift_duty_required') or 0))
        max_leave = st.number_input("Maximum Leave Per Day", value=int(existing_plan.get('maximum_leave_per_day') or 0))
        total_count = st.number_input("Total Count", value=int(existing_plan.get('total_count') or 0))
    with col2:
        ideal_weekly_off = st.number_input("Ideal Weekly Off Per Day", value=int(existing_plan.get('ideal_weekly_off_per_day') or 0))
        gen_shift = st.number_input("General Shift if no Weekly Off", value=int(existing_plan.get('general_shift_if_no_weekly_off') or 0))
    
    shift_duty_req_str = json.dumps(existing_plan.get('shift_duty_required', {}), indent=2)
    shift_duty_input = st.text_area("Shift Duty Required (JSON)", value=shift_duty_req_str, height=200)
    
    submitted = st.form_submit_button("Save Required Counts")
    if submitted:
        try:
            parsed_shift_duty = json.loads(shift_duty_input)
            row = {
                'role': selected_role,
                'effective_date': str(effective_date),
                'shift_duty_required': parsed_shift_duty,
                'total_shift_duty_required': int(total_shift_duty),
                'maximum_leave_per_day': int(max_leave),
                'ideal_weekly_off_per_day': int(ideal_weekly_off),
                'general_shift_if_no_weekly_off': int(gen_shift),
                'total_count': int(total_count)
            }
            res = client.table('role_required_counts').upsert(row).execute()
            st.success(f"Successfully updated required counts for {selected_role} effective {effective_date}!")
            st.rerun()
        except json.JSONDecodeError:
            st.error("Invalid JSON format for Shift Duty Required.")
        except Exception as e:
            st.error(f"Error saving: {e}")

st.markdown("#### Past Configurations")
history_res = client.table('role_required_counts').select('effective_date, total_count, total_shift_duty_required, maximum_leave_per_day, ideal_weekly_off_per_day').eq('role', selected_role).order('effective_date', desc=True).execute()
if history_res.data:
    st.dataframe(pd.DataFrame(history_res.data), use_container_width=True)
else:
    st.info("No historical configurations found.")
