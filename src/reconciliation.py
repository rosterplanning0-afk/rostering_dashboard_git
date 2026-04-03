import re

import pandas as pd


def load_employee_master(client):
    """Load employee master rows using the status-scoped queries used by the dashboard."""
    all_emp_rows = []
    for status_val in ["Active", "Inactive"]:
        try:
            res = (
                client.table("employees")
                .select("employee_id, name, department, designation, status, geo_location_link, latitude, longitude, full_address")
                .eq("status", status_val)
                .execute()
            )
            if res.data:
                all_emp_rows.extend(res.data)
        except Exception:
            pass
    return pd.DataFrame(all_emp_rows) if all_emp_rows else pd.DataFrame()


def filter_roster_scope(raw_df, config, selected_dept, selected_role):
    """Filter roster rows using the current department and designation sidebar state."""
    if raw_df.empty or selected_dept == "All":
        return raw_df.copy()

    allowed_roles = list(config["departments"][selected_dept].values())
    if selected_role != "All":
        pattern = re.escape(selected_role)
    else:
        pattern = "|".join(re.escape(role) for role in allowed_roles)

    mask = raw_df["crew_type"].fillna("").str.contains(pattern, case=False, na=False)
    return raw_df[mask].copy()


def filter_active_employees(emp_df, selected_dept, selected_role):
    """Filter employee master rows to the active population for the current sidebar scope."""
    if emp_df.empty:
        return emp_df.copy()

    filtered = emp_df.copy()
    if "status" in filtered.columns:
        filtered = filtered[filtered["status"] == "Active"]

    if selected_dept != "All" and "department" in filtered.columns:
        filtered = filtered[filtered["department"] == selected_dept]

    if selected_role != "All" and "designation" in filtered.columns:
        role_search = selected_role[:-1] if selected_role.endswith("s") else selected_role
        filtered = filtered[
            filtered["designation"].fillna("").str.contains(re.escape(role_search), case=False, na=False)
        ]

    return filtered.copy()


def get_roster_not_in_active(raw_df, active_emp_df, columns=None):
    """Return unique rostered staff that do not exist in the filtered active employee master."""
    if columns is None:
        columns = ["name", "emp_id", "crew_type", "duty_code_raw", "shift_start", "shift_end"]

    available_columns = [column for column in columns if column in raw_df.columns]
    if raw_df.empty:
        return pd.DataFrame(columns=available_columns)

    roster_only_df = raw_df.copy()
    roster_only_df["_emp_id_key"] = roster_only_df["emp_id"].fillna("").astype(str).str.strip()
    roster_only_df = roster_only_df[roster_only_df["_emp_id_key"] != ""]

    if active_emp_df.empty or "employee_id" not in active_emp_df.columns:
        active_keys = set()
    else:
        active_keys = set(active_emp_df["employee_id"].fillna("").astype(str).str.strip())

    roster_only_df = roster_only_df[~roster_only_df["_emp_id_key"].isin(active_keys)]
    if roster_only_df.empty:
        return pd.DataFrame(columns=available_columns)

    sort_columns = [column for column in ["name", "emp_id"] if column in roster_only_df.columns]
    if sort_columns:
        roster_only_df = roster_only_df.sort_values(sort_columns, na_position="last")

    roster_only_df = roster_only_df.drop_duplicates(subset=["_emp_id_key"])
    return roster_only_df[available_columns]