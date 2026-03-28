import streamlit as st
import pandas as pd
from src.supabase_client import get_supabase_client, fetch_all_by_date
from src.ui_components import render_sidebar
import plotly.express as px
import datetime
import re

# Render Global Sidebar and get config
config = render_sidebar()

st.title(":material/trending_up: Historical Trends")

def filter_data(df, config, selected_dept, selected_role):
    """Filters data based on global sidebar selections."""
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

@st.cache_data(show_spinner=False, ttl=60)
def load_trend_data(start_str, end_str, _config, selected_dept, selected_role):
    client = get_supabase_client()
    
    # Ensure raw strings are passed to Supabase
    raw_data = fetch_all_by_date(client, 'raw_roster_data', start_str, end_str, 'emp_id, date, crew_type')
    proc_data = fetch_all_by_date(client, 'processed_roster', start_str, end_str, 'emp_id, date, duty_category')
    
    if raw_data and proc_data:
        df_raw = pd.DataFrame(raw_data).drop_duplicates(subset=['emp_id', 'date'])
        df_proc = pd.DataFrame(proc_data).drop_duplicates(subset=['emp_id', 'date'])
        df = pd.merge(df_raw, df_proc, on=['emp_id', 'date'], how='inner')
        
        df = filter_data(df, _config, selected_dept, selected_role)
        if df.empty:
            return pd.DataFrame()
        
        df['date'] = pd.to_datetime(df['date'])
        
        # Case-insensitive leave detection helper
        def _is_leave(series):
            s = series.fillna('').str.strip()
            s_lower = s.str.lower()
            return (
                s_lower.str.contains('leave', regex=False) |
                s_lower.str.contains('holiday', regex=False) |
                (s_lower.str.contains('off', regex=False) & (s_lower != 'weekly off'))
            )
        
        # Dynamically calculate the metrics used in charting
        grouped = df.groupby('date').apply(lambda x: pd.Series({
            'on_duty_count': len(x[~_is_leave(x['duty_category']) & (x['duty_category'].str.strip().str.lower() != 'absent') & (x['duty_category'].str.strip() != 'Weekly Off')]),
            'general_shift_count': len(x[x['duty_category'].str.contains('General', na=False, case=False)]),
            'leave_count': len(x[_is_leave(x['duty_category']) & (x['duty_category'].str.strip().str.lower() != 'absent')]),
            'absent_count': len(x[x['duty_category'].str.strip().str.lower() == 'absent']),
            'weekly_off_count': len(x[x['duty_category'] == 'Weekly Off'])
        })).reset_index()
        
        return grouped.sort_values(by='date')
        
    return pd.DataFrame()

st.markdown("### Select Time Range")
c1, c2, c3 = st.columns([1, 1, 2])
with c1:
    default_start = datetime.datetime.now().date() - datetime.timedelta(days=30)
    start_date = st.date_input("From Date", default_start)
with c2:
    end_date = st.date_input("To Date", datetime.datetime.now().date())

if start_date > end_date:
    st.error("Error: 'From Date' must be before 'To Date'.")
else:
    with st.spinner("Fetching historical data..."):
        # Pass the session states as cache busters so changing the sidebar instantly updates the query
        selected_dept = st.session_state.get('selected_dept', 'All')
        selected_role = st.session_state.get('selected_role', 'All')
        df = load_trend_data(str(start_date), str(end_date), config, selected_dept, selected_role)

    if not df.empty:
        st.markdown("### On-Duty Staff Over Time")
        fig_duty = px.line(df, x='date', y='on_duty_count', markers=True, 
                           title="Daily On-Duty Count",
                           labels={'on_duty_count': 'Total Staff', 'date': 'Date'},
                           color_discrete_sequence=['#2563EB'])
        st.plotly_chart(fig_duty, use_container_width=True)
        
        st.markdown("### Absences & Leave Trends")
        # Melt dataframe to show multiple lines
        melted_df = df.melt(id_vars=['date'], value_vars=['leave_count', 'absent_count', 'weekly_off_count'],
                            var_name='Status', value_name='Count')
                            
        # Make status names prettier
        melted_df['Status'] = melted_df['Status'].map({
            'leave_count': 'Total Leaves',
            'absent_count': 'Absences',
            'weekly_off_count': 'Weekly Off (WO)'
        })
        
        fig_leaves = px.line(melted_df, x='date', y='Count', color='Status', markers=True,
                             title="Absences, Offs, and Leaves Breakdown",
                             color_discrete_map={'Total Leaves': '#F59E0B', 'Absences': '#EF4444', 'Weekly Off (WO)': '#64748B'})
        st.plotly_chart(fig_leaves, use_container_width=True)
        
        st.markdown("### Detailed Summary Table")
        display_df = df.copy()
        display_df['date'] = display_df['date'].dt.strftime('%Y-%m-%d')
        
        # Reorder columns to be more readable
        display_df = display_df[['date', 'on_duty_count', 'general_shift_count', 'leave_count', 'absent_count', 'weekly_off_count']]
        display_df.columns = ['Date', 'On Duty', 'General Shift', 'Leaves', 'Absent', 'Weekly Off']
        
        # Add Total row calculation
        display_df['Total'] = display_df['On Duty'] + display_df['Leaves'] + display_df['Absent'] + display_df['Weekly Off']
        
        st.dataframe(display_df, use_container_width=True, hide_index=True)
        
        st.markdown("---")
        st.markdown("### Employee Wise Shift Duty Matrix")
        st.markdown("Displays cumulative shift/duty breakdown per employee within the selected time range.")
        
        with st.spinner("Calculating employee-wise matrix..."):
            client = get_supabase_client()
            raw_data = fetch_all_by_date(client, 'raw_roster_data', str(start_date), str(end_date), 'emp_id, date, name, crew_type, shift_start, duty_code_raw')
            proc_data = fetch_all_by_date(client, 'processed_roster', str(start_date), str(end_date), 'emp_id, date, duty_category')
            
            if raw_data and proc_data:
                df_raw = pd.DataFrame(raw_data).drop_duplicates(subset=['emp_id', 'date'])
                df_proc = pd.DataFrame(proc_data).drop_duplicates(subset=['emp_id', 'date'])
                df_matrix = pd.merge(df_raw, df_proc, on=['emp_id', 'date'], how='inner')
                df_matrix = filter_data(df_matrix, config, selected_dept, selected_role)
                
                if not df_matrix.empty:
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
                            if code.startswith('M'): return 'M'
                            if code.startswith('E'): return 'E'
                            if code.startswith('N'): return 'N'
                            if code.startswith('G'): return 'G'
                            if pd.notna(start) and ':' in start:
                                try:
                                    hour = int(start.split(':')[0])
                                    if 3 <= hour < 8: return 'M'
                                    elif 8 <= hour < 14: return 'G'
                                    elif 14 <= hour < 20: return 'E'
                                    else: return 'N'
                                except: pass
                            return 'Other'

                    df_matrix['Duty_Type'] = df_matrix.apply(categorize_matrix_shift, axis=1)
                    pivot_df = pd.pivot_table(df_matrix, index=['emp_id', 'name', 'crew_type'], columns='Duty_Type', aggfunc='size', fill_value=0).reset_index()
                    pivot_df = pivot_df.rename(columns={'emp_id': 'Emp ID', 'name': 'Name', 'crew_type': 'Designation'})
                    
                    st.dataframe(pivot_df, use_container_width=True, hide_index=True)
                else:
                    st.info("No matrix data available.")
            else:
                st.info("No matrix data available.")
                
    else:
        st.info(f"No historical data available between {start_date} and {end_date}.")
