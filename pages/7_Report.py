import streamlit as st
import pandas as pd
import datetime
import io
import re
from src.supabase_client import get_supabase_client, fetch_all_by_date
from src.ui_components import render_sidebar

# Render Global Sidebar and get config
config = render_sidebar()

st.title("📝 Report Generator")
st.markdown("Generate dynamic reports for specific designations. This page is only accessible via direct URL.")

# Setup Filters
st.markdown("### Filters")
c1, c2, c3, c4 = st.columns(4)

with c1:
    default_start = datetime.datetime.now().date() - datetime.timedelta(days=60)
    start_date = st.date_input("From Date", default_start)
with c2:
    end_date = st.date_input("To Date", datetime.datetime.now().date())
with c3:
    dept_options = ["All"] + list(config['departments'].keys())
    selected_dept = st.selectbox("Department", dept_options)
with c4:
    role_options = ["All"]
    if selected_dept != "All":
        role_options += list(config['departments'][selected_dept].keys())
    selected_role = st.selectbox("Designation", role_options)

report_types = [
    "Night Shift Deficiency",
    "Leave & Absenteeism",
    "Weekly Off Compliance",
    "Shift Distribution",
    "Employee Wise Report"
]
selected_report = st.selectbox("Report Type", report_types)

def filter_data(df, config, selected_dept, selected_role):
    if selected_dept != "All" and not df.empty:
        allowed_roles = list(config['departments'][selected_dept].values())
        pattern = '|'.join([re.escape(role) for role in allowed_roles])
        
        if selected_role != "All":
            base_role = selected_role.rstrip('s')
            mask = df['crew_type'].str.contains(re.escape(base_role), case=False, na=False)
            df = df[mask]
        else:
            mask = df['crew_type'].str.contains(pattern, case=False, na=False)
            df = df[mask]
    return df

emp_id_input = ""
if selected_report == "Employee Wise Report":
    @st.cache_data(show_spinner=False, ttl=60)
    def get_employee_list(start_str, end_str, _config, selected_dept, selected_role):
        client = get_supabase_client()
        raw_data = fetch_all_by_date(client, 'raw_roster_data', start_str, end_str, 'emp_id, name, crew_type')
        if raw_data:
            df = pd.DataFrame(raw_data).drop_duplicates(subset=['emp_id'])
            df = filter_data(df, _config, selected_dept, selected_role)
            if not df.empty:
                df = df.sort_values(by='name')
                return df[['emp_id', 'name']].to_dict('records')
        return []

    employees = get_employee_list(str(start_date), str(end_date), config, selected_dept, selected_role)
    if not employees:
        st.warning("No employees found for the selected filters.")
    else:
        options = ["All"] + [f"{emp['emp_id']} - {emp['name']}" for emp in employees]
        selected_emp = st.selectbox("Select Employee (Optional)", options, help="Select a specific employee or 'All' to generate for everyone.")
        if selected_emp != "All":
            emp_id_input = selected_emp.split(" - ")[0]

@st.cache_data(show_spinner=False, ttl=60)
def load_report_data(start_str, end_str, _config, selected_dept, selected_role):
    client = get_supabase_client()
    raw_data = fetch_all_by_date(client, 'raw_roster_data', start_str, end_str, 'emp_id, date, name, crew_type, shift_start, duty_code_raw')
    proc_data = fetch_all_by_date(client, 'processed_roster', start_str, end_str, 'emp_id, date, duty_category')
    
    if raw_data and proc_data:
        df_raw = pd.DataFrame(raw_data).drop_duplicates(subset=['emp_id', 'date'])
        df_proc = pd.DataFrame(proc_data).drop_duplicates(subset=['emp_id', 'date'])
        df = pd.merge(df_raw, df_proc, on=['emp_id', 'date'], how='inner')
        df = filter_data(df, _config, selected_dept, selected_role)
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
        return df
    return pd.DataFrame()

def to_excel(data):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        if isinstance(data, pd.DataFrame):
            data.to_excel(writer, index=False, sheet_name='Report')
        elif isinstance(data, dict):
            for sheet_name, df in data.items():
                df.to_excel(writer, index=False, sheet_name=sheet_name[:31])
    processed_data = output.getvalue()
    return processed_data

if st.button("Generate Report", type="primary"):
    if start_date > end_date:
        st.error("Error: 'From Date' must be before 'To Date'.")
    else:
        with st.spinner("Fetching data and generating report..."):
            df = load_report_data(str(start_date), str(end_date), config, selected_dept, selected_role)
            
            if df.empty:
                st.warning("No data found for the selected filters.")
            else:
                # Helper function to categorize shift
                def categorize_matrix_shift(row):
                    crew = str(row.get('crew_type', '')).lower()
                    cat = str(row.get('duty_category', '')).strip()
                    code = str(row.get('duty_code_raw', '')).strip().upper()
                    start = str(row.get('shift_start', '')).strip()
                    
                    leave_codes = {'CL', 'LMCL', 'SL', 'EL', 'OH', 'PH', 'CO', 'LWP', 'LOP', 'ML', 'PL', 'SCL'}
                    if code in leave_codes: return code
                    if code == 'C/OFF': return 'CO'
                    
                    s_lower = cat.lower()
                    if 'casual leave' in s_lower: return 'CL'
                    if 'sick leave' in s_lower: return 'SL'
                    if 'earned leave' in s_lower: return 'EL'
                    if 'optional holiday' in s_lower: return 'OH'
                    if 'public holiday' in s_lower: return 'PH'
                    if 'compensatory' in s_lower or 'c/off' in s_lower: return 'CO'
                    if 'leave without pay' in s_lower or 'lop' in s_lower or 'lwp' in s_lower: return 'LWP/LOP'
                    if 'absent' in s_lower or code == 'A' or code == 'AB': return 'AB'
                    if 'weekly off' in s_lower or code == 'WO': return 'WO'
                    
                    is_to_ta = 'operator' in crew or 'attendant' in crew
                    if is_to_ta:
                        if pd.notna(start) and ':' in start:
                            try:
                                hour = int(start.split(':')[0])
                                if 3 <= hour < 8: return 'Early'
                                elif 8 <= hour < 14: return 'General'
                                elif 14 <= hour < 20: return 'Late'
                                else: return 'Night'
                            except: pass
                        if code.startswith('E'): return 'Early'
                        if code.startswith('G'): return 'General'
                        if code.startswith('L'): return 'Late'
                        if code.startswith('N'): return 'Night'
                        return 'Other'
                    else:
                        if code.startswith('M'): return 'Morning'
                        if code.startswith('E'): return 'Evening'
                        if code.startswith('N'): return 'Night'
                        if code.startswith('G'): return 'General'
                        if pd.notna(start) and ':' in start:
                            try:
                                hour = int(start.split(':')[0])
                                if 3 <= hour < 8: return 'Morning'
                                elif 8 <= hour < 14: return 'General'
                                elif 14 <= hour < 20: return 'Evening'
                                else: return 'Night'
                            except: pass
                        return 'Other'
                
                df['Duty_Type'] = df.apply(categorize_matrix_shift, axis=1)
                
                report_df = pd.DataFrame()
                
                if selected_report == "Night Shift Deficiency":
                    # Check who has 0 night shifts
                    pivot = df.pivot_table(index=['emp_id', 'name', 'crew_type'], columns='Duty_Type', aggfunc='size', fill_value=0).reset_index()
                    if 'Night' not in pivot.columns:
                        pivot['Night'] = 0
                    report_df = pivot[pivot['Night'] == 0].copy()
                    report_df = report_df[['emp_id', 'name', 'crew_type', 'Night']].rename(columns={'emp_id': 'Emp ID', 'name': 'Name', 'crew_type': 'Designation', 'Night': 'Night Shift Count'})
                    
                elif selected_report == "Leave & Absenteeism":
                    leave_types = ['CL', 'SL', 'EL', 'OH', 'PH', 'CO', 'LWP/LOP', 'AB']
                    pivot = df.pivot_table(index=['emp_id', 'name', 'crew_type'], columns='Duty_Type', aggfunc='size', fill_value=0).reset_index()
                    for lt in leave_types:
                        if lt not in pivot.columns:
                            pivot[lt] = 0
                    
                    pivot['Total Leaves/Absences'] = pivot[leave_types].sum(axis=1)
                    report_df = pivot[pivot['Total Leaves/Absences'] > 0].sort_values(by='Total Leaves/Absences', ascending=False)
                    report_df = report_df[['emp_id', 'name', 'crew_type', 'Total Leaves/Absences'] + leave_types]
                    report_df = report_df.rename(columns={'emp_id': 'Emp ID', 'name': 'Name', 'crew_type': 'Designation'})
                    
                elif selected_report == "Weekly Off Compliance":
                    # Look for WO gaps >= 7 days (meaning working 7+ consecutive days)
                    df_sorted = df.sort_values(by=['emp_id', 'date'])
                    
                    gap_records = []
                    for emp_id, emp_df in df_sorted.groupby('emp_id'):
                        emp_df = emp_df.reset_index(drop=True)
                        wo_dates = emp_df[emp_df['Duty_Type'] == 'WO']['date'].tolist()
                        
                        if not wo_dates:
                            gap = (emp_df['date'].max() - emp_df['date'].min()).days
                            if gap >= 7:
                                gap_records.append({
                                    'Emp ID': emp_id,
                                    'Name': emp_df['name'].iloc[0],
                                    'Designation': emp_df['crew_type'].iloc[0],
                                    'Max Days without WO': gap,
                                    'Note': 'No WO in selected period'
                                })
                        else:
                            max_gap = 0
                            # Check start to first WO
                            if (wo_dates[0] - emp_df['date'].min()).days > max_gap:
                                max_gap = (wo_dates[0] - emp_df['date'].min()).days
                            
                            # Check between WOs
                            for i in range(1, len(wo_dates)):
                                gap = (wo_dates[i] - wo_dates[i-1]).days - 1
                                if gap > max_gap:
                                    max_gap = gap
                                    
                            # Check last WO to end
                            if (emp_df['date'].max() - wo_dates[-1]).days > max_gap:
                                max_gap = (emp_df['date'].max() - wo_dates[-1]).days
                                
                            if max_gap >= 7:
                                gap_records.append({
                                    'Emp ID': emp_id,
                                    'Name': emp_df['name'].iloc[0],
                                    'Designation': emp_df['crew_type'].iloc[0],
                                    'Max Days without WO': max_gap,
                                    'Note': 'Has WO but with large gaps (>= 7 days)'
                                })
                                
                    report_df = pd.DataFrame(gap_records)
                    if not report_df.empty:
                        report_df = report_df.sort_values(by='Max Days without WO', ascending=False)
                        
                elif selected_report == "Shift Distribution":
                    pivot = df.pivot_table(index=['emp_id', 'name', 'crew_type'], columns='Duty_Type', aggfunc='size', fill_value=0).reset_index()
                    report_df = pivot.rename(columns={'emp_id': 'Emp ID', 'name': 'Name', 'crew_type': 'Designation'})
                
                elif selected_report == "Employee Wise Report":
                    if emp_id_input.strip():
                        df = df[df['emp_id'].astype(str).str.strip().str.upper() == emp_id_input.strip().upper()]
                        if df.empty:
                            st.warning(f"No records found for Employee ID: {emp_id_input}")
                            
                    if not df.empty:
                        details_df = df[['emp_id', 'name', 'crew_type', 'date', 'duty_category', 'shift_start', 'duty_code_raw', 'Duty_Type']].copy()
                        details_df['date'] = details_df['date'].dt.strftime('%Y-%m-%d')
                        details_df = details_df.rename(columns={
                            'emp_id': 'Emp ID', 'name': 'Name', 'crew_type': 'Designation', 'date': 'Date',
                            'duty_category': 'Category', 'shift_start': 'Sign ON', 'duty_code_raw': 'Duty Code', 'Duty_Type': 'Shift/Leave Type'
                        }).sort_values(by=['Emp ID', 'Date'])
                        
                        pivot = df.pivot_table(index=['emp_id', 'name', 'crew_type'], columns='Duty_Type', aggfunc='size', fill_value=0).reset_index()
                        pivot['Total Days'] = pivot.drop(columns=['emp_id', 'name', 'crew_type']).sum(axis=1)
                        summary_df = pivot.rename(columns={'emp_id': 'Emp ID', 'name': 'Name', 'crew_type': 'Designation'})
                        
                        report_df = summary_df  # Used for checking emptiness and preview
                        report_data_for_excel = {
                            'Shift Details': details_df,
                            'Summary': summary_df
                        }
                
                if not report_df.empty:
                    st.success(f"Successfully generated {selected_report}.")
                    
                    if selected_report == "Employee Wise Report":
                        st.markdown("#### Shift Details Preview")
                        st.dataframe(details_df.head(100), width='stretch', hide_index=True)
                        st.markdown("#### Summary Preview")
                        st.dataframe(summary_df, width='stretch', hide_index=True)
                        excel_data = to_excel(report_data_for_excel)
                    else:
                        st.dataframe(report_df, width='stretch', hide_index=True)
                        excel_data = to_excel(report_df)
                    
                    try:
                        st.download_button(
                            label="📥 Download Report as Excel",
                            data=excel_data,
                            file_name=f"{selected_report.replace(' ', '_')}_{start_date}_to_{end_date}.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                        )
                    except Exception as e:
                        st.warning(f"Could not generate Excel file. Ensure 'xlsxwriter' is installed. ({e})")
                else:
                    st.info(f"No records matched the criteria for the {selected_report}.")
