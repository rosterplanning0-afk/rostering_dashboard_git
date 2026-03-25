# 📊 Executive Dashboards Integration Plan (Next.js & Supabase)

**Project:** `footplate-inspection-sys/other_website`
**Target Stack:** Next.js (App Router), React, Supabase, Tailwind CSS, Recharts
**Objective:** Port the Python/Streamlit analytical dashboards (Daily Overview, Historical Trends, and Fatigue & Fairness Management) into the existing Next.js web application with strict Role-Based Access Control (RBAC) enforced within the Sidebar and Data Fetching layers.

---

## 1. Role-Based Access Control (RBAC) Architecture

The application will restrict data visibility and sidebar navigation based on the user's role defined in the `users` or `employees` database table.

### Access Tiers
1. **CXO (Chief Executive Officer / C-Suite)**
   - **Access Level:** Global (Company-wide)
   - **Data Visibility:** Unrestricted. Can view aggregated metrics and filter by *any* department across the entire organization.
   - **Sidebar Navigation:** Full access to all modules.

2. **HoD (Head of Department)**
   - **Access Level:** Departmental
   - **Data Visibility:** Restricted to their specific Department (e.g., only "Train Operations"). Total metrics reflect only their department's staff.
   - **Sidebar Navigation:** Full access to modules, but dropdowns are locked to their assigned Department.

3. **Manager**
   - **Access Level:** Team / Designation Level
   - **Data Visibility:** Restricted strictly to their Assigned Department **AND** Assigned Employees under specific Designations (e.g., A Manager assigned to "Train Operators" in "Train Operations" sees only those specific employees).
   - **Sidebar Navigation:** Access to Daily Overview and specific drill-downs, locked to their exact team scope.

4. **Admin / System Administrator**
   - **Access Level:** Unrestricted Technical Access
   - **Data Visibility:** Unrestricted (Same as CXO).
   - **Sidebar Navigation:** Full access + System Settings / Data Sync capabilities.

### Implementation Strategy for RBAC
- **Next.js Middleware:** Protect routes (`/dashboard/daily-overview`, etc.) so unauthorized roles are redirected.
- **Supabase Row Level Security (RLS):** 
  - The safest approach: `SELECT` policies on `employees`, `raw_roster_data`, and `processed_roster` tables that dynamically check `auth.uid()` against the user's assigned role and scope to implicitly filter data at the database level.
  - Alternatively (if RLS is too complex for aggregations): Use Server actions / API routes in Next.js using the Supabase Service Role key, verifying the user's JWT and applying hardcoded `WHERE` filters (e.g., `.eq('department', user.department)`) before passing data to the frontend.

---

## 2. Component & Page Architecture

### A. Sidebar Navigation (`src/components/Sidebar.tsx`)
- Reads user profile from Context/Supabase Session.
- Dynamically renders links:
  - `Daily Overview`
  - `Historical Trends`
  - `Fatigue Management`
- Hides/locks filter UI components based on the role.

### B. Daily Overview (`src/app/dashboard/daily-overview/page.tsx`)
- **UI Layout:**
  - **Top Row (Cards):** Total Active Employees, Total Roster Staff, Unassigned Gap.
  - **Second Row (Cards):** Total On-Duty (Active shifts excluding leaves/offs), Absentees, Total Leaves, Weekly Off.
  - **Main Area (Tabs/Sections):** 
    - *Staff Reconciliation:* Pie charts (Recharts) for Duty Distribution (Shift, Leaves, Standby).
    - *Shift Timeline (Bar Chart):* Breakdown of Early / General / Late / Night shifts.
    - *Data Table:* Paginated specific roster details.
- **Data Logic Translation:**
  - Translate the Python Pandas logic into TypeScript array reductions.
  - Instead of fetching *all* data to the client, perform the grouping via a Supabase Postgres RPC (Remote Procedure Call) or fetch raw arrays and use standard JS `.filter()` and `.reduce()`.

### C. Historical Trends (`src/app/dashboard/historical-trends/page.tsx`)
- **UI Layout:**
  - **Filters:** Date Picker (Range), Department/Role filters (if authorized).
  - **Line Charts:**
    - Daily On-Duty counts over 30 days.
    - Multi-line chart tracking Absences vs. Leaves vs. Weekly Offs.
- **Data Logic Translation:**
  - Needs a heavy grouping query. Best practice is to create a Supabase Postgres View (`v_daily_metrics`) that pre-aggregates the `on_duty_count`, `leave_count`, `absent_count` by `date`. The Next.js frontend simply queries this view, guaranteeing fast load times.

### D. Fatigue & Fairness Management (`src/app/dashboard/fatigue/page.tsx`)
- **UI Layout:**
  - **Metrics:** Rest Violation Counts, Consecutive Night Shifts, Weekend Equivalents.
  - **Alerts Table:** Highlighting specific `emp_id`s that trigger fatigue warnings.
- **Data Logic Translation:**
  - *Chronological Sorting:* Fetch data ordered by `emp_id` and `date`.
  - *Looping:* Translate the Python iteration that detects < 12-hour rest, 6+ consecutive shifts, and consecutive nights into a robust TypeScript utility function (`calculateFatigue(rosterArray)`).

---

## 3. Recommended Phased Execution Plan

**Phase 1: Foundation & RBAC (Weeks 1-2)**
- Setup Supabase Auth state in the Next.js target (`other_website`).
- Design the Database RBAC model (adding `role`, `assigned_department`, `assigned_designations` to the user profile table).
- Build the dynamic Sidebar component that conditionally renders links and scope text.

**Phase 2: Data Hooks & Postgres Views (Weeks 2-3)**
- Avoid parsing massive JSON arrays in the browser. Write Postgres SQL Views in Supabase to replicate the Python Pandas aggregation logic (esp. for Historical Trends).
- Create Supabase client data-fetching hooks in Next.js (`useDailyRoster`, `useHistoricalTrends`).

**Phase 3: The Daily Overview (Weeks 3-4)**
- Build the UI shell for the Daily Overview using Tailwind CSS + Shadcn UI (Cards, Tabs, Data Tables).
- Implement the "On-Duty vs Leaves" logic precisely as defined in Python (`~isin(['Absent', 'Weekly Off', 'Uncategorized'])`).
- Integrate Recharts line/pie visualisations.

**Phase 4: Historical & Fatigue Modules (Weeks 4-5)**
- Build the Historical Trends view (connecting Date Range pickers to data hooks).
- Port the complex Fatigue calculation loops from Python to a pure TypeScript server utility.
- Build the visual warnings interface for Managers / HoDs.

---

## 4. Specific Technical Translation Notes (Python -> TS)

**Python (Pandas):**
```python
leave_names = ['Casual Leave', 'Earned Leave']
on_duty = len(roster_df[~roster_df['duty_category'].isin(leave_names)])
```

**TypeScript Equivalent (Client/Server Side Processing):**
```typescript
const leaveNames = ['Casual Leave', 'Earned Leave'];
const onDutyCount = rosterData.filter(row => 
  !leaveNames.includes(row.duty_category) && 
  row.duty_category !== 'Absent' && 
  row.duty_category !== 'Weekly Off'
).length;
```
*(Note: Pushing this logic into a Supabase Postgres View or RPC is highly recommended for performance over large datasets).*
