import streamlit as st
import pandas as pd
import datetime
import json
import os
import csv
from src.processor import process_new_rosters
from src.ui_components import render_sidebar
from src.supabase_client import get_supabase_client

config = render_sidebar()
client = get_supabase_client()

st.title(":material/admin_panel_settings: Administration")
st.markdown("---")
st.markdown("### :material/sync: Roster Synchronization")

sync_options = {
    "Last 8 Hours": 480,
    "Last 24 Hours": 1440,
    "Last 7 Days": 10080,
    "Last 30 Days": 43200,
    "All Time (Full Sync)": -1
}

selected_sync_window = st.selectbox(
    "Select Sync Time Window",
    options=list(sync_options.keys()),
    index=0,
    help="Select how far back to look for modified rosters in Google Drive."
)

if st.button(":material/sync: Sync New Rosters", type="primary"):
    with st.spinner(f"Fetching from Drive ({selected_sync_window})..."):
        selected_minutes = sync_options[selected_sync_window]
        is_force_all = (selected_minutes == -1)
        result = process_new_rosters(force_all=is_force_all, time_window_minutes=selected_minutes if not is_force_all else 480)
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

st.write(f"Editing counts for **{selected_role}** effective **{effective_date}**")

col1, col2 = st.columns(2)
with col1:
    total_count = st.number_input("Total Count", value=int(existing_plan.get('total_count') or 0))
with col2:
    gen_shift = st.number_input("General Shift if no Weekly Off", value=int(existing_plan.get('general_shift_if_no_weekly_off') or 0))

shift_duty_req_str = json.dumps(existing_plan.get('shift_duty_required', {}), indent=2)
shift_duty_input = st.text_area("Shift Duty Required (JSON)", value=shift_duty_req_str, height=200)

try:
    parsed_shift_duty = json.loads(shift_duty_input)
    calc_shift_duty = sum(int(v) for v in parsed_shift_duty.values())
except Exception:
    parsed_shift_duty = existing_plan.get('shift_duty_required', {})
    calc_shift_duty = 0

calc_weekly_off = round(total_count * 0.15)
calc_max_leave = total_count - calc_shift_duty - calc_weekly_off - gen_shift

col3, col4 = st.columns(2)
with col3:
    total_shift_duty = st.number_input("Total Shift Duty Required", value=calc_shift_duty, disabled=True)
    max_leave = st.number_input("Maximum Leave Per Day", value=calc_max_leave, disabled=True)
with col4:
    ideal_weekly_off = st.number_input("Ideal Weekly Off Per Day", value=calc_weekly_off, disabled=True)

if st.button("Save Required Counts", type="primary"):
    try:
        valid_json = json.loads(shift_duty_input)
        row = {
            'role': selected_role,
            'effective_date': str(effective_date),
            'shift_duty_required': valid_json,
            'total_shift_duty_required': int(calc_shift_duty),
            'maximum_leave_per_day': int(calc_max_leave),
            'ideal_weekly_off_per_day': int(calc_weekly_off),
            'general_shift_if_no_weekly_off': int(gen_shift),
            'total_count': int(total_count)
        }
        res = client.table('role_required_counts').upsert(row).execute()
        st.success(f"Successfully updated required counts for {selected_role} effective {effective_date}!")
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

st.markdown("---")
st.markdown("### :material/category: Categorize Unmapped Duties")

# Gather existing categories from config.json and categorized_duties.csv
existing_categories = set()
for mapping in config.get("duty_mapping", []):
    existing_categories.add(mapping.get("category"))
    
CSV_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "categorized_duties.csv")
if os.path.exists(CSV_PATH):
    try:
        df_csv = pd.read_csv(CSV_PATH)
        if len(df_csv.columns) >= 2:
            existing_categories.update(df_csv.iloc[:, 1].dropna().astype(str).unique())
    except Exception:
        pass

existing_categories = sorted([c for c in existing_categories if c and c.lower() != 'nan'])

# Query processed_roster for Uncategorized (using pagination to bypass 1000 row limit)
all_uncat_data = []
offset = 0
limit = 1000
while True:
    res_uncat = client.table("processed_roster").select("duty_code").eq("duty_category", "Uncategorized").range(offset, offset + limit - 1).execute()
    data = res_uncat.data
    if not data:
        break
    all_uncat_data.extend(data)
    if len(data) < limit:
        break
    offset += limit

if all_uncat_data:
    uncat_codes = sorted(list(set(row["duty_code"] for row in all_uncat_data if row.get("duty_code"))))
else:
    uncat_codes = []

if not uncat_codes:
    st.info("No uncategorized duties found in the database. Great job!")
else:
    st.write(f"Found **{len(uncat_codes)}** uncategorized duty code(s).")
    
    with st.form("categorize_form"):
        mappings_to_save = {}
        for code in uncat_codes:
            st.markdown(f"**Code:** `{code}`")
            col1, col2 = st.columns(2)
            with col1:
                sel_cat = st.selectbox(f"Select Category for {code}", ["— Skip —"] + existing_categories + ["Create New..."], key=f"sel_{code}")
            with col2:
                new_cat = st.text_input(f"New Category Name (if 'Create New...')", key=f"new_{code}")
            
            if sel_cat != "— Skip —":
                final_cat = new_cat.strip() if sel_cat == "Create New..." else sel_cat
                if final_cat:
                    mappings_to_save[code] = final_cat
            st.markdown("---")
            
        submit_mapping = st.form_submit_button("Save & Re-sync", type="primary")
            
        if submit_mapping:
            if not mappings_to_save:
                st.warning("No mappings to save.")
            else:
                # Append to CSV
                file_exists = os.path.exists(CSV_PATH)
                try:
                    with open(CSV_PATH, 'a', newline='', encoding='utf-8') as f:
                        writer = csv.writer(f)
                        if not file_exists:
                            writer.writerow(["Uncategorized list:", "categorized"])
                        for code, cat in mappings_to_save.items():
                            writer.writerow([code, cat])
                    
                    # Instead of full sync, update the database directly for speed
                    from src.pdf_parser import categorize_duty, _INACTIVE_KEYWORDS
                    with st.spinner("Applying new categories to the database..."):
                        success_count = 0
                        for code, cat in mappings_to_save.items():
                            # Infer status
                            cat_lower = cat.lower()
                            status = 'Inactive' if any(kw in cat_lower for kw in _INACTIVE_KEYWORDS) else 'Active'
                            
                            client.table("processed_roster").update({
                                "duty_category": cat,
                                "status": status
                            }).eq("duty_code", code).execute()
                            success_count += 1
                            
                    st.success(f"Successfully saved and applied {success_count} mappings! Data has been updated.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error saving mappings: {e}")
