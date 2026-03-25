import streamlit as st
import pandas as pd
from src.supabase_client import get_supabase_client, fetch_all_by_date
from src.ui_components import render_sidebar
import plotly.express as px
import datetime
import re

st.set_page_config(page_title="Historical Trends", page_icon=":material/trending_up:", layout="wide")

# Render Global Sidebar and get config
config = render_sidebar()

st.title(":material/trending_up: Historical Trends")

def filter_data(df, config):
    """Filters data based on global sidebar selections."""
    selected_dept = st.session_state.get('selected_dept', 'All')
    selected_role = st.session_state.get('selected_role', 'All')
    
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
def load_trend_data(start_str, end_str, _config, _dept, _role):
    client = get_supabase_client()
    
    # Ensure raw strings are passed to Supabase
    raw_data = fetch_all_by_date(client, 'raw_roster_data', start_str, end_str, 'emp_id, date, crew_type')
    proc_data = fetch_all_by_date(client, 'processed_roster', start_str, end_str, 'emp_id, date, duty_category')
    
    if raw_data and proc_data:
        df_raw = pd.DataFrame(raw_data).drop_duplicates(subset=['emp_id', 'date'])
        df_proc = pd.DataFrame(proc_data).drop_duplicates(subset=['emp_id', 'date'])
        df = pd.merge(df_raw, df_proc, on=['emp_id', 'date'], how='inner')
        
        df = filter_data(df, config)
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
                (s_lower.str.contains('off', regex=False) & ~s.str.contains('Weekly Off', regex=False))
            ) & ~s.str.contains('Weekly Off', regex=False)
        
        # Dynamically calculate the metrics used in charting
        grouped = df.groupby('date').apply(lambda x: pd.Series({
            'on_duty_count': len(x[~_is_leave(x['duty_category']) & (x['duty_category'].str.strip().str.lower() != 'absent') & (x['duty_category'].str.strip() != 'Weekly Off') & (x['duty_category'].str.strip() != 'Uncategorized')]),
            'general_shift_count': len(x[x['duty_category'].str.contains('General', na=False, case=False)]),
            'leave_count': len(x[_is_leave(x['duty_category']) & (x['duty_category'].str.strip().str.lower() != 'absent')]),
            'absent_count': len(x[x['duty_category'].isin(['Absent', 'DEROSTER'])]),
            'weekly_off_count': len(x[x['duty_category'] == 'Weekly Off']),
            'standby_count': len(x[x['duty_category'].str.contains('Standby', na=False, case=False)]),
            'depot_count': len(x[x['duty_category'].str.contains('Depot', na=False, case=False)])
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
        display_df = display_df[['date', 'on_duty_count', 'general_shift_count', 'leave_count', 'absent_count', 'weekly_off_count', 'standby_count', 'depot_count']]
        display_df.columns = ['Date', 'On Duty', 'General Shift', 'Leaves', 'Absent', 'Weekly Off', 'Standby', 'Depot']
        
        st.dataframe(display_df, use_container_width=True, hide_index=True)
        
    else:
        st.info(f"No historical data available between {start_date} and {end_date}.")
