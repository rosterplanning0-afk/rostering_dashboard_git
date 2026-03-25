import streamlit as st
import pandas as pd
from src.supabase_client import get_supabase_client, fetch_all_by_date
from src.ui_components import render_sidebar
from datetime import datetime, timedelta
import plotly.express as px
import plotly.graph_objects as go

st.set_page_config(page_title="Fairness & Fatigue", page_icon=":material/balance:", layout="wide")

# Render Global Sidebar and get config
config = render_sidebar()
st.markdown("### Select Time Range")
c1, c2, c3 = st.columns([1, 1, 2])
with c1:
    default_start = datetime.now().date().replace(day=1)
    start_date = st.date_input("From Date", default_start)
with c2:
    end_date = st.date_input("To Date", datetime.now().date())

st.title(":material/balance: Fairness & Fatigue Management")
st.markdown("Analyze duty equitability, total working hours, and individual employee monthly rosters.")

@st.cache_data(show_spinner=False)
def load_monthly_data(start_str, end_str):
    client = get_supabase_client()
    raw_data = fetch_all_by_date(client, 'raw_roster_data', start_str, end_str)
    proc_data = fetch_all_by_date(client, 'processed_roster', start_str, end_str)
    
    if raw_data and proc_data:
        df_raw = pd.DataFrame(raw_data).drop_duplicates(subset=['emp_id', 'date'])
        df_proc = pd.DataFrame(proc_data).drop_duplicates(subset=['emp_id', 'date'])
        df_proc = df_proc[['date', 'emp_id', 'duty_category', 'status']]
        merged = pd.merge(df_raw, df_proc, on=['date', 'emp_id'], how='inner')
        return merged
    return pd.DataFrame()

if start_date > end_date:
    st.error("'From Date' must be before 'To Date'.")
    df = pd.DataFrame()
else:
    with st.spinner("Fetching roster data..."):
        df = load_monthly_data(str(start_date), str(end_date))

if not df.empty:
    st.sidebar.markdown("---")
    st.sidebar.markdown("### :material/person: Employee Filter")
    
    selected_dept = st.session_state.get('selected_dept', 'All')
    selected_role = st.session_state.get('selected_role', 'All')
    
    filtered_df = df.copy()
    
    if selected_dept != "All":
        allowed_roles = list(config['departments'][selected_dept].values())
        import re
        pattern = '|'.join([re.escape(role) for role in allowed_roles])
        
        if selected_role != "All":
            base_role = selected_role.rstrip('s')
            mask = filtered_df['crew_type'].str.contains(re.escape(base_role), case=False, na=False)
            filtered_df = filtered_df[mask]
        else:
            mask = filtered_df['crew_type'].str.contains(pattern, case=False, na=False)
            filtered_df = filtered_df[mask]
    
    emp_list = ["All"] + sorted(filtered_df['name'].unique().tolist())
    selected_employee = st.sidebar.selectbox("Select Employee", emp_list)
    
    if selected_employee != "All":
        filtered_df = filtered_df[filtered_df['name'] == selected_employee]

    st.markdown("---")
    st.subheader("Master Roster Grid View")
    
    # Pre-process dates and categories for styling and rules
    def categorize_shift_time(start_time_str):
        if not start_time_str or pd.isna(start_time_str):
            return 'Leave/Off/Other'
        try:
            hour = int(start_time_str.split(':')[0])
            if 3 <= hour < 8: return 'Early'
            elif 8 <= hour < 14: return 'General'
            elif 14 <= hour < 20: return 'Late'
            elif 20 <= hour or hour < 3: return 'Night'
            else: return 'Other'
        except:
            return 'Other'

    filtered_df['shift_period'] = filtered_df['shift_start'].apply(categorize_shift_time)
    filtered_df['date'] = pd.to_datetime(filtered_df['date'])
    filtered_df = filtered_df.sort_values(by=['emp_id', 'date'])

    # Fatigue Rule Evaluation Engine
    fatigue_rules = config.get("fatigue_rules", [])
    
    # Create a composite display string that holds both the visual text and the metadata needed for styling
    # Format: "DUTY_CODE::CATEGORY::SHIFT_PERIOD::VIOLATION_FLAG"
    def enrich_cell(row):
        code = row['duty_code_raw'] if pd.notna(row['duty_code_raw']) else ""
        
        # Add shift times if they exist (SMR-22 (14:00-22:00))
        if code and "WO" not in code and "Leave" not in code and "Absent" not in code and "Optional" not in code:
            if pd.notna(row.get('shift_start')) and pd.notna(row.get('shift_end')):
                try:
                    s = str(row['shift_start'])[:5]
                    e = str(row['shift_end'])[:5]
                    if s != "00:00" or e != "00:00":
                        code = f"{code} ({s}-{e})"
                except:
                    pass
                    
        return f"{code}::{row['duty_category']}::{row['shift_period']}::0"
        
    filtered_df['enriched_cell'] = filtered_df.apply(enrich_cell, axis=1)

    # Flag Violations chronologically per employee
    for emp_id, group in filtered_df.groupby('emp_id'):
        prev_shift = None
        for idx, row in group.iterrows():
            current_shift = row['shift_period']
            violation = 0
            
            if prev_shift:
                for rule in fatigue_rules:
                    if prev_shift in rule['previous_shift_types'] and current_shift in rule['current_shift_types']:
                        violation = 1
                        break
                        
            if violation:
                parts = filtered_df.at[idx, 'enriched_cell'].split('::')
                parts[3] = "1"
                filtered_df.at[idx, 'enriched_cell'] = "::".join(parts)
                
            prev_shift = current_shift if current_shift != 'Leave/Off/Other' else prev_shift

    # Calculate daily working hours FIRST so we can pivot it later
    def calculate_hours(row):
        if pd.isna(row['shift_start']) or pd.isna(row['shift_end']):
            return 0
        try:
            start_str = str(row['shift_start'])
            end_str = str(row['shift_end'])
            fmt_start = '%H:%M:%S' if len(start_str.split(':')) == 3 else '%H:%M'
            fmt_end = '%H:%M:%S' if len(end_str.split(':')) == 3 else '%H:%M'
            t1 = datetime.strptime(start_str, fmt_start)
            t2 = datetime.strptime(end_str, fmt_end)
            if t2 < t1:
                t2 += timedelta(days=1)
            diff = (t2 - t1).total_seconds() / 3600
            return diff
        except:
            return 0
            
    filtered_df['working_hours'] = filtered_df.apply(calculate_hours, axis=1)

    # Convert shift times to proper datetimes for chronological rest tracking
    def parse_shift_datetime(d, t_str):
        if pd.isna(t_str) or pd.isna(d): return pd.NaT
        t_str = str(t_str)[:5]
        if t_str == "00:00": return pd.NaT
        try:
            return pd.to_datetime(f"{d.strftime('%Y-%m-%d')} {t_str}")
        except:
            return pd.NaT

    filtered_df['start_dt'] = filtered_df.apply(lambda r: parse_shift_datetime(r['date'], r['shift_start']), axis=1)
    filtered_df['end_dt'] = filtered_df.apply(lambda r: parse_shift_datetime(r['date'], r['shift_end']), axis=1)
    mask_cross = filtered_df['end_dt'] < filtered_df['start_dt']
    filtered_df.loc[mask_cross, 'end_dt'] += timedelta(days=1)

    filtered_df = filtered_df.sort_values(by=['emp_id', 'date'])
    filtered_df['last_duty_end'] = filtered_df.groupby('emp_id')['end_dt'].transform(lambda x: x.ffill().shift(1))
    filtered_df['rest_hours'] = (filtered_df['start_dt'] - filtered_df['last_duty_end']).dt.total_seconds() / 3600

    def format_hours_or_leave(row):
        cat = str(row.get('duty_category', ''))
        short_cat = ""
        cat_lower = cat.lower() if cat else ''
        is_leave_or_off = pd.notna(cat) and (cat in ['Weekly Off', 'Sick Leave/Casual Leave', 'Casual Leave', 'Earned Leave', 'Absent', 'Public Holiday', 'Optional Holiday'] or 'leave' in cat_lower or 'holiday' in cat_lower or ('off' in cat_lower and cat != 'Weekly Off'))
        
        if is_leave_or_off:
            if cat == "Weekly Off": short_cat = "WO"
            elif "Casual" in cat or "Sick" in cat: short_cat = "CL"
            elif "Earned" in cat: short_cat = "EL"
            elif cat == "Public Holiday": short_cat = "PH"
            elif cat == "Optional Holiday": short_cat = "OH"
            else: short_cat = "ABS"
            
        if row['working_hours'] > 0:
            val = f"{row['working_hours']:.1f}h"
            if pd.notna(row.get('rest_hours')) and row['rest_hours'] > 0:
                val += f" ⏱️{row['rest_hours']:.1f}h"
            return val
        elif is_leave_or_off:
            return short_cat
        return ""

    filtered_df['hours_str'] = filtered_df.apply(format_hours_or_leave, axis=1)

    # Generate complete date range strings from start_date to end_date
    date_range = pd.date_range(start=start_date, end=end_date)
    full_date_strs = date_range.strftime('%d.%m.\n%a').str.upper().tolist()

    # Pre-format the date string for joining
    filtered_df['date_str'] = filtered_df['date'].dt.strftime('%d.%m.\n%a').str.upper()

    # 1. Pivot to Main Duty Grid
    grid = filtered_df.pivot_table(index=['emp_id', 'name'], columns='date_str', values='enriched_cell', aggfunc='first')
    
    # Reindex to ensure all dates are present even if empty
    for col in full_date_strs:
        if col not in grid.columns:
            grid[col] = ""
    # Reorder columns and flatten index
    grid = grid.reset_index()
    # Enforce order: emp_id, name, then dates
    grid = grid[['emp_id', 'name'] + full_date_strs]
    
    # Custom Styler for Roster
    def style_roster_cell(val):
        if pd.isna(val) or val == "":
            return 'background-color: #f8f9fa; color: #f8f9fa;'
            
        parts = str(val).split('::')
        if len(parts) != 4:
            return ''
            
        code, category, period, is_violation = parts
        cat_lower = str(category).lower() if category else ''
        
        css = "color: white; font-weight: bold; text-align: center; border-radius: 4px; padding: 4px;"
        
        if is_violation == "1":
            css += "background-color: #8b0000; border: 2px solid #ff0000;" 
        elif category in ['Weekly Off', 'Public Holiday', 'Optional Holiday'] or 'holiday' in cat_lower or ('off' in cat_lower and category != 'Weekly Off'):
            css += "background-color: #78c257;" 
        elif category in ['Absent', 'Sick Leave/Casual Leave', 'Casual Leave', 'Earned Leave'] or ('leave' in cat_lower and 'holiday' not in cat_lower):
            css += "background-color: #d12c2c;" 
        else:
            css += "background-color: #2980b9;" 
            
        return css

    def format_cell_text(val):
        if pd.isna(val) or val == "":
            return ""
        parts = str(val).split('::')
        if len(parts) == 4:
            text = parts[0]
            if parts[3] == "1":
                return f"⚠️ {text}"
            return text
        return val

    subset_cols = full_date_strs
    styled_grid = grid.style.map(style_roster_cell, subset=subset_cols).format(format_cell_text, subset=subset_cols)
    
    # --- Weekly Hours Tracker & Cumulative Cell Format Logic ---
    filtered_df = filtered_df.sort_values(by=['emp_id', 'date'])
    filtered_df['is_wo'] = filtered_df['duty_category'] == 'Weekly Off'
    filtered_df['cycle_id'] = filtered_df.groupby('emp_id')['is_wo'].cumsum()
    filtered_df['cumulative_cycle_hours'] = filtered_df.groupby(['emp_id', 'cycle_id'])['working_hours'].cumsum()

    def format_cumulative_hours(row):
        val = str(row['hours_str'])
        if row['working_hours'] > 0:
            cum = row['cumulative_cycle_hours']
            alert = "⏱️" if cum <= 48 else "⚠️"
            return f"{val} {alert} {cum:.1f}h"
        return val

    filtered_df['hours_str'] = filtered_df.apply(format_cumulative_hours, axis=1)

    work_days_only = filtered_df[filtered_df['working_hours'] > 0]
    if not work_days_only.empty:
        cycle_summary = work_days_only.groupby(['emp_id', 'name', 'cycle_id']).agg(
            cycle_hours=('working_hours', 'sum'),
            cycle_start=('date', 'min'),
            cycle_end=('date', 'max'),
            shifts_in_cycle=('date', 'count')
        ).reset_index()
        max_cycle_hours = cycle_summary['cycle_hours'].max()
        cycle_summary['cycle_start'] = cycle_summary['cycle_start'].dt.strftime('%d-%m-%Y')
        cycle_summary['cycle_end'] = cycle_summary['cycle_end'].dt.strftime('%d-%m-%Y')
        cycle_summary['Alert'] = cycle_summary['cycle_hours'].apply(lambda x: "⚠️ > 48h" if x > 48 else "OK")
    else:
        cycle_summary = pd.DataFrame(columns=['emp_id', 'name', 'cycle_start', 'cycle_end', 'shifts_in_cycle', 'cycle_hours', 'Alert'])
        max_cycle_hours = 0
    
    # 2. Pivot to Hours Grid
    hours_grid = filtered_df.pivot_table(index=['emp_id', 'name'], columns='date_str', values='hours_str', aggfunc='first')
    # Reindex
    for col in full_date_strs:
        if col not in hours_grid.columns:
            hours_grid[col] = ""
    hours_grid = hours_grid.reset_index()[['emp_id', 'name'] + full_date_strs]

    def style_hours_cell(val):
        if pd.isna(val) or val == "":
            return 'background-color: #f8f9fa; color: #f8f9fa; text-align: center;'
        val_str = str(val)
        if val_str in ['WO', 'PH'] or 'WO' in val_str:
            return 'background-color: #78c257; color: white; font-weight: bold; text-align: center; border-radius: 4px; padding: 4px;'
        if val_str in ['CL', 'EL', 'ABS']:
            return 'background-color: #d12c2c; color: white; font-weight: bold; text-align: center; border-radius: 4px; padding: 4px;'
        if '⚠️' in val_str:
            return 'background-color: #e74c3c; color: white; font-weight: bold; text-align: center; border-radius: 4px; padding: 4px;'
        return 'background-color: #2980b9; color: white; font-weight: bold; text-align: center; border-radius: 4px; padding: 4px;'

    styled_hours_grid = hours_grid.style.map(style_hours_cell, subset=subset_cols).format(lambda x: x if pd.notna(x) else "", subset=subset_cols)

    # Display in Tabs
    t1, t2, t3 = st.tabs(["Master Roster Grid", "Daily Working Hours", "Weekly Hours Compliance Report"])
    with t1:
        st.dataframe(styled_grid, use_container_width=True, height=600, hide_index=True)
    with t2:
        st.dataframe(styled_hours_grid, use_container_width=True, height=600, hide_index=True)
    
    # Calculate Total Working Hours and Fairness KPIs
    st.markdown("### :material/bar_chart: Metrics & KPIs")
    
    # Summarize per employee
    emp_summary = filtered_df.groupby(['name', 'emp_id']).agg(
        total_hours=('working_hours', 'sum'),
        total_shifts=('date', lambda x: x.count())
    ).reset_index()
    
    emp_summary = emp_summary.sort_values(by='total_hours', ascending=False)
    
        
    # Populate the newly created compliance tab
    with t3:
        st.markdown("#### :material/table_chart: Weekly Operators Compliance Matrix")
        st.markdown("Consolidated Excel-style matrix tracking consecutive hours bounded by Weekly Offs against the 48-Hour rule.")
        
        if not cycle_summary.empty:
            # 1. Relative Week Numbers for each employee
            cycle_summary['week_num'] = cycle_summary.groupby('emp_id').cumcount() + 1
            cycle_summary['date_range'] = cycle_summary['cycle_start'] + " to " + cycle_summary['cycle_end']
            
            # 2. Pivot Dates
            pivot_dates = cycle_summary.pivot(index=['emp_id', 'name'], columns='week_num', values='date_range')
            pivot_dates = pivot_dates.rename(columns=lambda x: f"Week_{x}_Date")
            
            # 3. Pivot Hours
            pivot_hours = cycle_summary.pivot(index=['emp_id', 'name'], columns='week_num', values='cycle_hours')
            pivot_hours = pivot_hours.rename(columns=lambda x: f"Week_{x}_Hrs")
            
            # 4. Join components
            wide_df = pivot_dates.join(pivot_hours).reset_index()
            
            # 5. Build MultiIndex columns
            cols_tuples = [('Employee ID', ''), ('Employee name', '')]
            ordered_flat_cols = ['emp_id', 'name']
            
            max_weeks = cycle_summary['week_num'].max()
            for w in range(1, max_weeks + 1):
                if f"Week_{w}_Date" in wide_df.columns:
                    ordered_flat_cols.append(f"Week_{w}_Date")
                    cols_tuples.append((f'Week {w}', 'Date'))
                if f"Week_{w}_Hrs" in wide_df.columns:
                    ordered_flat_cols.append(f"Week_{w}_Hrs")
                    cols_tuples.append((f'Week {w}', 'Working Hrs'))
                    
            wide_df = wide_df[ordered_flat_cols]
            wide_df.columns = pd.MultiIndex.from_tuples(cols_tuples)
            
            # 6. Apply Conditional Styler
            def highlight_hours(val):
                if pd.isna(val) or val == "":
                    return ""
                try:
                    if float(val) > 48:
                        return 'background-color: red; color: white; font-weight: bold; text-align: center;'
                except:
                    pass
                return 'text-align: center;'
            
            styled_df = wide_df.style
            for w in range(1, max_weeks + 1):
                hrs_col = (f'Week {w}', 'Working Hrs')
                if hrs_col in wide_df.columns:
                    styled_df = styled_df.map(highlight_hours, subset=[hrs_col])
                    styled_df = styled_df.format(lambda x: f"{x:.0f}hrs" if pd.notna(x) else "", subset=[hrs_col])
                
                date_col = (f'Week {w}', 'Date')
                if date_col in wide_df.columns:
                    styled_df = styled_df.format(lambda x: x if pd.notna(x) else "", subset=[date_col])
                    
            st.dataframe(styled_df, use_container_width=True, hide_index=True)
        else:
            st.info("No cycle data available under the current filters.")

    # Top Level KPIs
    c1, c2, c3 = st.columns(3)
    avg_hours = emp_summary['total_hours'].mean() if len(emp_summary) > 0 else 0
    max_hours = emp_summary['total_hours'].max() if len(emp_summary) > 0 else 0
    
    c1.metric("Average Working Hours (Selected Group)", f"{avg_hours:.1f} hrs")
    c2.metric("Highest Monthly Hours (Individual)", f"{max_hours:.1f} hrs")
    c3.metric("Highest Continuous Weekly Hours", f"{max_cycle_hours:.1f} hrs", help="Max hours worked consecutively between Weekly Offs globally.")
    
    st.markdown("---")
    
    c_left, c_right = st.columns([1,1])
    
    with c_left:
        st.markdown("#### Total Working Hours Distribution")
        fig_hours = px.histogram(emp_summary, x='total_hours', nbins=15, 
                                 title="Distribution of Working Hours",
                                 labels={'total_hours': 'Total Monthly Hours', 'count': 'Number of Employees'},
                                 color_discrete_sequence=['#2563EB'])
        st.plotly_chart(fig_hours, use_container_width=True)
        
    with c_right:
        st.markdown("#### Duty Type Allocation Check")
        # Ensure fairness among early/late/night
        def categorize_shift_time(start_time_str):
            if not start_time_str or pd.isna(start_time_str):
                return 'Leave/Off/Other'
            try:
                hour = int(start_time_str.split(':')[0])
                if 3 <= hour < 8: return 'Early'
                elif 8 <= hour < 14: return 'General'
                elif 14 <= hour < 20: return 'Late'
                elif 20 <= hour or hour < 3: return 'Night'
                else: return 'Other'
            except:
                return 'Other'
                
        filtered_df['shift_period'] = filtered_df['shift_start'].apply(categorize_shift_time)
        shift_mix = filtered_df['shift_period'].value_counts().reset_index()
        shift_mix.columns = ['Shift Type', 'Total Instances']
        
        fig_pie = px.pie(shift_mix, values='Total Instances', names='Shift Type', hole=0.4,
                         color_discrete_sequence=["#2563EB", "#3B82F6", "#93C5FD", "#F59E0B"])
        st.plotly_chart(fig_pie, use_container_width=True)
        
    
    if selected_employee != "All" and not cycle_summary.empty:
        st.markdown("#### Dynamic Weekly Hours Monitor")
        st.markdown("Cumulative working hours between Weekly Off instances for the selected employee.")
        emp_cycles = cycle_summary[cycle_summary['name'] == selected_employee].copy()
        if not emp_cycles.empty:
            emp_cycles['Cycle Name'] = emp_cycles.apply(lambda x: f"{x['cycle_start']} - {x['cycle_end']}", axis=1)
            emp_cycles['Status'] = emp_cycles['cycle_hours'].apply(lambda x: "High Workload (>48h)" if x > 48 else "Normal")
            fig_cycles = px.bar(emp_cycles, x='Cycle Name', y='cycle_hours', text='cycle_hours',
                                color='Status',
                                color_discrete_map={"Normal": "#2563EB", "High Workload (>48h)": "#EF4444"},
                                title="Consecutive Working Hours per Work Week")
            fig_cycles.update_traces(texttemplate='%{text:.1f}h', textposition='outside')
            st.plotly_chart(fig_cycles, use_container_width=True)

    st.markdown("#### Detailed Hours Leaderboard")
    st.dataframe(emp_summary, use_container_width=True)

else:
    st.info("No data available for the selected month window.")
