import streamlit as st
import pandas as pd
from src.supabase_client import get_supabase_client
from src.reconciliation import filter_active_employees, filter_roster_scope, load_employee_master
from src.ui_components import render_sidebar
import plotly.express as px
import datetime
import re

st.set_page_config(page_title="Daily Overview", page_icon=":material/calendar_today:", layout="wide")

# Render Global Sidebar and get config
config = render_sidebar()
selected_date = st.session_state.get('selected_date', datetime.datetime.now().date())

def load_data(date_str):
    client = get_supabase_client()
    
    # Fetch processed roster
    roster_res = client.table('processed_roster').select('*').eq('date', date_str).execute()
    roster_df = pd.DataFrame(roster_res.data) if roster_res.data else pd.DataFrame()
    if not roster_df.empty: roster_df = roster_df.drop_duplicates(subset=['emp_id', 'date'])
    
    # Fetch raw roster for displaying table
    raw_res = client.table('raw_roster_data').select('*').eq('date', date_str).execute()
    raw_df = pd.DataFrame(raw_res.data) if raw_res.data else pd.DataFrame()
    if not raw_df.empty: raw_df = raw_df.drop_duplicates(subset=['emp_id', 'date'])
    
    # Fetch all employees using the same helper used by reconciliation views.
    emp_df = load_employee_master(client)

    
    # Merge crew_type into roster_df so breakdown logic works
    if not roster_df.empty and not raw_df.empty:
        roster_df = pd.merge(roster_df, raw_df[['emp_id', 'crew_type']], on='emp_id', how='left')
    
    return roster_df, raw_df, emp_df


def apply_filters(df, raw_df, emp_df, config):
    """Filters dataframes based on global sidebar selections."""
    selected_dept = st.session_state.get('selected_dept', 'All')
    selected_role = st.session_state.get('selected_role', 'All')

    emp_df = filter_active_employees(emp_df, selected_dept, selected_role)
    raw_df = filter_roster_scope(raw_df, config, selected_dept, selected_role)

    if selected_dept != "All":
        valid_emp_ids = set(raw_df['emp_id'].astype(str)) if not raw_df.empty else set()
        if not df.empty:
            df = df[df['emp_id'].astype(str).isin(valid_emp_ids)]

    return df, raw_df, emp_df

def is_leave_mask(series):
    """Case-insensitive mask for ALL leave / holiday categories (excl. Weekly Off)."""
    s = series.fillna('').str.strip()
    s_lower = s.str.lower()
    return (
        s_lower.str.contains('leave', regex=False) |
        s_lower.str.contains('holiday', regex=False) |
        (s_lower.str.contains('off', regex=False) & ~s.str.contains('Weekly Off', regex=False))
    ) & ~s.str.contains('Weekly Off', regex=False)

def categorize_shift_time(row):
    cat = str(row.get('duty_category', ''))
    
    if cat == 'Weekly Off':
        return 'Weekly Off'
        
    leave_types = ['Casual Leave', 'Earned Leave', 'Compensatory Leave', 'Compensatory OFF', 'Sick Leave', 'Absent', 'Public Holiday', 'Maternity Leave', 'Paternity Leave', 'Optional Holiday', 'Compassionate Leave']
    if cat in leave_types or "Leave" in cat or ("OFF" in cat and cat != "Weekly Off") or "holiday" in cat.lower():
        return 'Leaves'
        
    if cat == 'General Duty':
        return 'General shifts'

    start_time_str = row.get('shift_start')
    if not start_time_str or pd.isna(start_time_str):
        return 'No Time/Other'
        
    try:
        hour = int(str(start_time_str).split(':')[0])
        if 3 <= hour < 8:
            return 'Early'
        elif 8 <= hour < 14:
            return 'General shifts'
        elif 14 <= hour < 20:
            return 'Late'
        elif 20 <= hour or hour < 3:
            return 'Night'
        else:
            return 'Unknown'
    except:
        return 'Unknown'


def get_required_plan(config, selected_role):
    """Get required duty targets for the selected role from config."""
    role_plan = config.get('required_counts', {}).get(selected_role, {})
    duty_required = role_plan.get('shift_duty_required', {})
    duty_required_norm = {str(k).strip().lower(): v for k, v in duty_required.items()}
    return role_plan, duty_required_norm


def get_required_for_duty(duty_name, duty_required_norm):
    """Map duty variants to a single required-count key."""
    duty_key = str(duty_name).strip().lower()
    aliases = {
        'protection duty rrts': 'rrts spare/protection duty',
        'protection duty mrts': 'mrts spare/protection duty',
    }
    duty_key = aliases.get(duty_key, duty_key)
    return duty_required_norm.get(duty_key, '')


def get_capacity_counts(config, selected_dept, selected_role):
    """Return planned and approved counts aggregated for the current filter scope."""
    capacity_cfg = config.get('staff_capacity_counts', {})
    departments_cfg = config.get('departments', {})

    designations = []
    if selected_role != 'All':
        designations = [selected_role]
    elif selected_dept != 'All':
        designations = list(departments_cfg.get(selected_dept, {}).values())
    else:
        for dept_roles in departments_cfg.values():
            designations.extend(list(dept_roles.values()))

    planned = 0
    approved = 0
    for designation in designations:
        role_capacity = capacity_cfg.get(designation, {})
        planned += int(role_capacity.get('planned_count', 0) or 0)
        approved += int(role_capacity.get('approved_count', 0) or 0)

    return planned, approved


def style_shift_shortfall(row):
    """Highlight Headcount cell in red when headcount mismatches required."""
    styles = [''] * len(row)
    if 'Headcount' not in row.index or 'Required Count' not in row.index:
        return styles

    headcount = pd.to_numeric(row['Headcount'], errors='coerce')
    required = pd.to_numeric(row['Required Count'], errors='coerce')
    if pd.notna(headcount) and pd.notna(required) and headcount < required:
        head_idx = list(row.index).index('Headcount')
        styles[head_idx] = 'background-color: #f8d7da; color: #8b1e24; font-weight: 700;'
    return styles

st.title(f":material/calendar_today: Daily Staff Overview - {selected_date}")

# Load data for selected date
with st.spinner("Loading data from Supabase..."):
    roster_df, raw_df, emp_df = load_data(str(selected_date))

# Apply global filters
roster_df, raw_df, emp_df = apply_filters(roster_df, raw_df, emp_df, config)

tab1, tab2, tab3 = st.tabs(["📊 Daily Overview", "⏰ Shift Analysis", "✈️ Leave Analytics"])

with tab1:
    if not raw_df.empty:
        st.markdown("### :material/bar_chart: Staff Reconciliation Overview")
        selected_dept = st.session_state.get('selected_dept', 'All')
        selected_role = st.session_state.get('selected_role', 'All')
        
        # Recompute metrics dynamically using case-insensitive leave detection
        total_active_employees = len(emp_df) if not emp_df.empty else 0
        total_rostered = len(raw_df) if not raw_df.empty else 0
        unaccounted = max(0, total_active_employees - total_rostered) if total_active_employees > 0 else 0
        planned_count, approved_count = get_capacity_counts(config, selected_dept, selected_role)
        planned_gap = total_active_employees - planned_count
        approved_gap = total_active_employees - approved_count
        
        if not roster_df.empty:
            duty_col = roster_df['duty_category']
            leave_mask = is_leave_mask(duty_col)
            absent_mask = duty_col.str.strip().str.lower() == 'absent'
            wo_mask = duty_col.str.strip() == 'Weekly Off'
            uncat_mask = duty_col.str.strip() == 'Uncategorized'
            on_duty = len(roster_df[~leave_mask & ~absent_mask & ~wo_mask & ~uncat_mask])
            absences = len(roster_df[absent_mask])
            leaves = len(roster_df[leave_mask & ~absent_mask])
            weekly_off = len(roster_df[wo_mask])
        else:
            on_duty = absences = leaves = weekly_off = 0
        
        # Top level balancing metrics
        m1, m2, m3, m4, m5 = st.columns(5)
        with m1:
            st.metric("Total Active Employees (DB)", total_active_employees)
        with m2:
            st.metric("Total Staff on Roster", total_rostered)
        with m3:
            st.metric("Unassigned / Gap", unaccounted, delta=-unaccounted if unaccounted > 0 else 0, delta_color="inverse")
        with m4:
            st.metric("Planned Count / Gap", planned_count, delta=planned_gap)
        with m5:
            st.metric("Approved Count / Gap", approved_count, delta=approved_gap)
            
        st.markdown("#### Staff Breakdown (From Roster)")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            st.metric("Total On-Duty", on_duty)
        with c2:
            st.metric("Total Absentees", absences)
        with c3:
            st.metric("Total Leaves (Excl. WO)", leaves)
        with c4:
            st.metric("Weekly Off (WO)", weekly_off)
            
        st.markdown("---")
        
        # Make the expander dynamic based on the selected role
        required_plan, duty_required_norm = get_required_plan(config, selected_role)
        expander_title = "📋 Detailed Duty Breakdown"
        if selected_dept != "All":
            expander_title += f" ({selected_role})"
            
        with st.expander(expander_title, expanded=False):
            if not roster_df.empty:
                # Group by category
                counts = roster_df['duty_category'].value_counts().to_dict()
                
                leave_types = ['Casual Leave', 'Earned Leave', 'Compensatory Leave', 'Compensatory OFF', 'Sick Leave', 'Absent', 'Public Holiday', 'Maternity Leave', 'Paternity Leave', 'Optional Holiday', 'Compassionate Leave']
                
                shift_counts = {}
                leave_counts = {}
                wo_counts = {}
                
                for k, v in counts.items():
                    k_lower = str(k).lower() if k else ''
                    if k == 'Weekly Off':
                        wo_counts[k] = v
                    elif k in leave_types or "leave" in k_lower or ("off" in k_lower and k != "Weekly Off") or "holiday" in k_lower:
                        leave_counts[k] = v
                    elif k == 'Uncategorized':
                        # Break down uncategorized duties by their raw duty code
                        uncat_df = roster_df[roster_df['duty_category'] == 'Uncategorized']
                        uncat_raw_counts = uncat_df['duty_code'].value_counts().to_dict()
                        for raw_code, count_val in uncat_raw_counts.items():
                            clean_code = str(raw_code).split('\n')[0].strip() if pd.notna(raw_code) else 'Unknown'
                            shift_counts[f"Uncategorized ({clean_code})"] = count_val
                    else:
                        shift_counts[k] = v
                        
                colA, colB, colC = st.columns(3)
                
                with colA:
                    st.markdown("#### Shift Duty")
                    if selected_role != 'All' and not required_plan:
                        st.caption("Required targets are not configured for this designation in config.json.")
                    if shift_counts:
                        desired_order = [
                            "RRTS Duty", "RRTS duty", "RRTS stand by duty", "RRTS Spare/protection duty", "Protection Duty RRTS",
                            "MRTS Duty", "MRTS duty", "MRTS stand by duty", "MRTS Spare/protection duty", "Protection Duty MRTS",
                            "On Duty", "Shuttle Duty", "Crew Duty", "Depot Duty", "Technical Spare (General shift)",
                            "General Duty", "General Spare/protection duty", "Training", "Simulator", "Testing", "Safety Training"
                        ]
                        
                        ordered_shifts = []
                        for item in desired_order:
                            if item in shift_counts:
                                ordered_shifts.append(item)
                        
                        for item in sorted(shift_counts.keys()):
                            if item not in ordered_shifts:
                                ordered_shifts.append(item)
                                
                        shift_df = pd.DataFrame({
                            "Duty Type": ordered_shifts,
                            "Headcount": [shift_counts[k] for k in ordered_shifts],
                            "Required Count": [get_required_for_duty(k, duty_required_norm) for k in ordered_shifts],
                        })
                        
                        total_sum = sum(shift_counts.values())
                        shift_df.loc[len(shift_df)] = [
                            "Total Shift Duty",
                            total_sum,
                            required_plan.get('total_shift_duty_required', ''),
                        ]
                        
                        st.dataframe(
                            shift_df.style.apply(style_shift_shortfall, axis=1),
                            hide_index=True,
                            use_container_width=True,
                        )
                        st.caption("Headcount highlighted in red indicates mismatch versus Required Count.")
                        if required_plan.get('total_count'):
                            st.caption(f"Total Count (Required): {required_plan.get('total_count')}")
                    else:
                        st.info("No shift duties.")
                
                with colB:
                    st.markdown("#### Leaves")
                    if leave_counts:
                        leave_df = pd.DataFrame({"Leave Type": list(leave_counts.keys()), "Headcount": list(leave_counts.values())})
                        leave_df.loc[len(leave_df)] = ["Total Leaves", sum(leave_counts.values())]
                        st.dataframe(leave_df, hide_index=True, use_container_width=True)
                        if required_plan.get('maximum_leave_per_day') is not None:
                            st.caption(
                                f"Maximum Leave that can be given Per day: {required_plan.get('maximum_leave_per_day')}"
                            )
                        if required_plan.get('general_shift_if_no_weekly_off') is not None:
                            st.caption(
                                f"If no Weekly Off, keep 1 Leave and {required_plan.get('general_shift_if_no_weekly_off')} in General Duty."
                            )
                    else:
                        st.info("No leaves.")
                
                with colC:
                    st.markdown("#### Weekly Off")
                    if wo_counts:
                        wo_df = pd.DataFrame({"Type": list(wo_counts.keys()), "Headcount": list(wo_counts.values())})
                        wo_df.loc[len(wo_df)] = ["Total", sum(wo_counts.values())]
                        st.dataframe(wo_df, hide_index=True, use_container_width=True)
                        if required_plan.get('ideal_weekly_off_per_day') is not None:
                            st.caption(
                                f"Weekly Off target per day: {required_plan.get('ideal_weekly_off_per_day')}"
                            )
                        if required_plan.get('general_shift_if_no_weekly_off') is not None:
                            st.caption(
                                f"Fallback rule: if Weekly Off is 0, keep 1 Leave and {required_plan.get('general_shift_if_no_weekly_off')} in General Duty."
                            )
                    else:
                        st.info("No weekly offs.")
                        
                st.caption(f"**Total Headcount verification:** {len(roster_df)}")
            else:
                st.info("No data found in the current filtered view.")

        st.markdown("---")
        
        st.markdown("#### Duty Distribution")
        if not roster_df.empty:
            cat_counts = roster_df['duty_category'].value_counts().reset_index()
            cat_counts.columns = ['Category', 'Count']
            
            fig = px.pie(cat_counts, values='Count', names='Category', 
                         hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
            st.plotly_chart(fig, use_container_width=True)

        st.markdown("---")
        st.markdown("### 📋 Rostered Personnel List")
        if not raw_df.empty:
            # Merge raw_df with roster_df to get duty_category
            personnel_df = pd.merge(raw_df, roster_df[['emp_id', 'duty_category']], on='emp_id', how='left')
            
            # Filter by duty_category similar to Raw Data Explorer
            category_filter = st.selectbox("Filter by Category", ['All'] + list(personnel_df['duty_category'].unique()))
            
            filtered_personnel_df = personnel_df.copy()
            if category_filter != 'All':
                filtered_personnel_df = filtered_personnel_df[filtered_personnel_df['duty_category'] == category_filter]
            
            st.dataframe(
                filtered_personnel_df[['name', 'emp_id', 'duty_code_raw', 'shift_start', 'shift_end', 'crew_type', 'duty_category']], 
                hide_index=True, use_container_width=True
            )

    else:
        st.info(f"No roster data uploaded for {selected_date}.")

with tab2:
    if not raw_df.empty:
        st.markdown("### Shift Timeline Distribution")
        st.info("**Shift Time Definitions:** Early (`03:00 - 07:59`) | General (`08:00 - 13:59`) | Late (`14:00 - 19:59`) | Night (`20:00 - 02:59`)", icon="ℹ️")
        
        # Build the shift df combining raw schedule with categorized status
        shift_df = pd.merge(raw_df, roster_df[['emp_id', 'duty_category']], on='emp_id', how='left')
        shift_df['duty_category'] = shift_df['duty_category'].fillna('Unknown')
        shift_df['shift_category'] = shift_df.apply(categorize_shift_time, axis=1)
        
        shift_counts_bar = shift_df['shift_category'].value_counts().reset_index()
        shift_counts_bar.columns = ['Time of Day', 'Total Staff']
        
        order_map = {'Early': 1, 'General shifts': 2, 'Late': 3, 'Night': 4, 'Leaves': 5, 'Weekly Off': 6, 'No Time/Other': 7, 'Unknown': 8}
        shift_counts_bar['order_val'] = shift_counts_bar['Time of Day'].map(order_map).fillna(9)
        shift_counts_bar = shift_counts_bar.sort_values(by='order_val')
        
        fig_shift = px.bar(shift_counts_bar, x='Time of Day', y='Total Staff', text='Total Staff',
                     color='Time of Day', color_discrete_sequence=px.colors.sequential.Viridis)
        st.plotly_chart(fig_shift, use_container_width=True)
        
        st.markdown("### Active Personnel by Shift")
        st.dataframe(shift_df[['name', 'emp_id', 'shift_start', 'shift_end', 'shift_category', 'crew_type', 'duty_category']], 
                     use_container_width=True, hide_index=True)
    else:
        st.info(f"No shifts found for {selected_date}.")

with tab3:
    if not roster_df.empty:
        st.markdown("### Leave Breakdown")
        # Case-insensitive: captures Public holiday, Optional holiday, etc.
        leave_df_full = roster_df[is_leave_mask(roster_df['duty_category']) | (roster_df['duty_category'].str.strip().str.lower() == 'absent')]
        
        if not leave_df_full.empty:
            leave_counts_pie = leave_df_full['duty_category'].value_counts().reset_index()
            leave_counts_pie.columns = ['Leave Type', 'Count']
            
            colL1, colL2 = st.columns([1, 1])
            with colL1:
                fig_leave = px.pie(leave_counts_pie, values='Count', names='Leave Type', hole=0.3,
                             title="Distribution of Absences & Leaves",
                             color_discrete_sequence=["#F97316", "#F59E0B", "#FBBF24", "#FDE68A"])
                st.plotly_chart(fig_leave, use_container_width=True)
                
            with colL2:
                st.markdown("#### Staff on Leave / Absent")
                st.dataframe(leave_df_full[['emp_id', 'duty_category', 'duty_code']], use_container_width=True, hide_index=True)
        else:
            st.info(f"No leaves or absences logged for {selected_date} matching the current filters.")
    else:
        st.info(f"No leaves or absences logged for {selected_date} matching the current filters.")
