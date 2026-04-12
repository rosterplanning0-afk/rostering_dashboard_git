import pdfplumber
import pandas as pd
import re
from datetime import datetime
import json
import os

# Load Configuration
CONFIG_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'config.json')
with open(CONFIG_PATH, 'r') as f:
    CONFIG = json.load(f)

# ---------------------------------------------------------------------------
# Load categorized_duties.csv for exact-match duty overrides
# The CSV has two columns: duty_code (col 0) and category (col 1)
# ---------------------------------------------------------------------------
_CATEGORIZED_DUTIES_CSV = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'categorized_duties.csv')
_EXACT_DUTY_MAP: dict = {}  # duty_code (uppercase) → category string

if os.path.exists(_CATEGORIZED_DUTIES_CSV):
    try:
        _csv_df = pd.read_csv(_CATEGORIZED_DUTIES_CSV)
        # The first column header is "Uncategorized list:" and the second is "categorized"
        cols = _csv_df.columns.tolist()
        for _, csv_row in _csv_df.iterrows():
            raw_code = str(csv_row[cols[0]]).strip()
            raw_cat = str(csv_row[cols[1]]).strip()
            if raw_code and raw_cat and raw_code.lower() != 'nan' and raw_cat.lower() != 'nan':
                _EXACT_DUTY_MAP[raw_code.upper()] = raw_cat
        print(f"[pdf_parser] Loaded {len(_EXACT_DUTY_MAP)} exact duty overrides from categorized_duties.csv")
    except Exception as e:
        print(f"[pdf_parser] Warning: Could not load categorized_duties.csv: {e}")

# ---------------------------------------------------------------------------
# Crew-type resolver: splits composite crew_type strings like
# "Crew Controller, Train Operators" by looking up the individual employee's
# designation in the employees table.
#
# Strategy: fetch designation per emp_id using a pinpoint .eq() filter.
# This bypasses Supabase RLS policies that block unfiltered/dept-level reads.
# Results are cached in-memory for the lifetime of this module (one sync run).
# ---------------------------------------------------------------------------

_emp_designation_cache: dict = {}   # emp_id (str) → designation (str) | None
_supabase_client_ref = None         # module-level client reuse


def _get_employee_designation(emp_id: str) -> str | None:
    """
    Returns the `designation` string for the given emp_id from the employees
    table, or None if not found. Uses an in-memory cache so each employee
    is only queried once per parser session.
    """
    global _supabase_client_ref, _emp_designation_cache

    if emp_id in _emp_designation_cache:
        return _emp_designation_cache[emp_id]

    try:
        if _supabase_client_ref is None:
            from src.supabase_client import get_supabase_client
            _supabase_client_ref = get_supabase_client()

        res = _supabase_client_ref.table('employees') \
            .select('designation') \
            .eq('employee_id', emp_id) \
            .limit(1) \
            .execute()

        if res.data and res.data[0].get('designation'):
            designation = res.data[0]['designation']
        else:
            designation = None

    except Exception as e:
        print(f"[pdf_parser] Warning: Could not fetch designation for {emp_id}: {e}")
        designation = None

    _emp_designation_cache[emp_id] = designation
    return designation


# Maps of known composites → (train_operator_resolution, crew_controller_resolution, default_resolution)
# default_resolution is used when the employee is not found in the employees table.
_COMPOSITE_MAP = {
    # Both designations in Train Operations — distinguish by actual employees table designation
    'crew controller, train operators':    ('Train Operators', 'Crew Controller', 'Crew Controller'),
    'train operators, crew controller':    ('Train Operators', 'Crew Controller', 'Crew Controller'),
    # Traffic Controller lives in a different dept from Train Ops
    'traffic controller, train operators': ('Train Operators', 'Traffic Controller', 'Traffic Controller'),
    'train operators, traffic controller': ('Train Operators', 'Traffic Controller', 'Traffic Controller'),
    # OCC-only composites – single resolution regardless of designation
    'depot controller, traffic controller':         ('Depot Controller', 'Depot Controller', 'Depot Controller'),
    'rolling stock controller, station controller': ('Rolling Stock Controller', 'Rolling Stock Controller', 'Rolling Stock Controller'),
}


def resolve_crew_type(crew_type: str, emp_id: str) -> str:
    """
    Resolves a composite crew_type like 'Crew Controller, Train Operators'
    to a single canonical value based on the employee's actual designation
    in the employees table.

    Logic:
      1. If crew_type has no comma → already single, return as-is.
      2. Look up employee's designation from DB cache.
      3. Match designation against known options:
           – 'Train Operator'  → return train_ops resolution
           – 'Crew Controller' → return cc resolution
           – unknown/not found → return default (first listed role)
    """
    if ',' not in crew_type:
        return crew_type  # fast-path – already a single canonical role

    key = crew_type.lower().strip()
    if key not in _COMPOSITE_MAP:
        # Unknown composite – return the first listed role as safe default
        print(f"[pdf_parser] Unknown composite crew_type: '{crew_type}'. Using first listed.")
        return crew_type.split(',')[0].strip()

    train_op_val, cc_val, default_val = _COMPOSITE_MAP[key]

    designation = _get_employee_designation(str(emp_id))

    if designation is None:
        # Employee not in DB – use the default (first listed role in composite)
        print(f"[pdf_parser] emp_id {emp_id} not found in employees table. Using default: {default_val}")
        return default_val

    desig_lower = designation.lower()
    if 'train operator' in desig_lower:
        return train_op_val
    elif 'crew controller' in desig_lower:
        return cc_val
    elif 'train attendant' in desig_lower:
        return 'Train Attendants'
    else:
        # Designation found but doesn't match either option → safe default
        print(f"[pdf_parser] emp_id {emp_id} has designation '{designation}' "
              f"— does not clearly match options for '{crew_type}'. Using: {default_val}")
        return default_val

# Leave/inactive category keywords for status inference from CSV overrides
_INACTIVE_KEYWORDS = {'leave', 'holiday', 'absent', 'off', 'weekly off', 'compensatory', 'deroster'}

def categorize_duty(duty_string):
    """Maps a raw duty string (which might contain linebreaks/times) to a standardized category.
    
    Priority order:
      1. Exact match from categorized_duties.csv (_EXACT_DUTY_MAP)
      2. Regex patterns from config.json (duty_mapping)
      3. Fallback to 'Uncategorized'
    """
    if not isinstance(duty_string, str) or not duty_string.strip():
        return 'Unknown', 'Inactive'
        
    duty_lines = str(duty_string).strip().split('\n')
    duty_code = duty_lines[0].strip() # Usually the first line is the duty code
    
    # Priority 1: Check exact match from categorized_duties.csv
    csv_category = _EXACT_DUTY_MAP.get(duty_code.upper())
    if csv_category:
        # Infer status: if the category name suggests leave/absence, mark Inactive
        cat_lower = csv_category.lower()
        status = 'Inactive' if any(kw in cat_lower for kw in _INACTIVE_KEYWORDS) else 'Active'
        return csv_category, status
    
    # Priority 2: Regex patterns from config.json
    for mapping in CONFIG.get('duty_mapping', []):
        if re.search(mapping['pattern'], duty_code, re.IGNORECASE):
            return mapping['category'], mapping['status']
            
    return 'Uncategorized', 'Inactive'

def extract_shift_times(duty_string):
    """Extracts shift start and end times from the duty string if present."""
    if not isinstance(duty_string, str):
        return None, None
        
    # Look for HH:MM-HH:MM pattern
    match = re.search(r'(\d{2}:\d{2})\s*-\s*(\d{2}:\d{2})', duty_string)
    if match:
        return match.group(1), match.group(2)
    return None, None
    

def parse_ivu_pdf(pdf_path, fallback_date=None, file_name=None):
    """
    Extracts tables from IVU roster PDF.
    Format based on `example_train_operator.pdf`:
    Col 0: Employee (Name)
    Col 1: Personnel Number (Emp ID)
    Col 2: Scheduling row
    Col 3: Mon. xx.xx (Duty + Time) -> e.g. "SM-10\n06:29-14:29"
    Col 4: Paid time
    """
    roster_date = fallback_date
    crew_type_global = "Train Operators"
    
    # Smart Tagging: Infer crew type from filename using Config mappings
    if file_name:
        fname_upper = file_name.upper().replace('.PDF', '')
        for dept, roles in CONFIG.get('departments', {}).items():
            for short_form, full_name in roles.items():
                # Check for explicit separators like -SC, _SC, or isolated SC
                if f"-{short_form}" in fname_upper or f"_{short_form}" in fname_upper or f" {short_form} " in fname_upper:
                    crew_type_global = full_name
                    # Break out early if found
                    break
    
    extracted_data = []

    with pdfplumber.open(pdf_path) as pdf:
        if len(pdf.pages) > 0:
            first_page_text = pdf.pages[0].extract_text()
            if first_page_text:
                # e.g. "4 Mar 2026 - 4 Mar 2026" or "1 Dec 2025 - 31 Dec 2025"
                date_match = re.search(r'(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})\s*-\s*\d{1,2}\s+[A-Za-z]{3}\s+\d{4}', first_page_text)
                crew_match = re.search(r'CREW TYPE:\s*(.*)', first_page_text)
                if date_match:
                    try:
                        # Extract the components
                        d_str = date_match.group(1).zfill(2) # PAD to "01" if it was "1"
                        m_str = date_match.group(2)
                        y_str = date_match.group(3)
                        roster_date = datetime.strptime(f"{d_str} {m_str} {y_str}", '%d %b %Y').date()
                    except ValueError as e:
                        print(f"Date match error: {e}")
                        pass
                if crew_match:
                    crew_type_global = crew_match.group(1).strip()
                    
        if not roster_date:
            roster_date = datetime.now().date()
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                header_dates = {}
                
                for row in table:
                    # Capture Header Row to map horizontal dates
                    if row and row[0] and "Employee" in str(row[0]):
                        # For each column from index 3 onwards, try to parse a date
                        for col_idx in range(3, len(row)):
                            header_str = str(row[col_idx]).replace('\n', '')
                            # Example: Sun. 01.02 or Tue.01.04 meaning Day 01 Month 04
                            date_match = re.search(r'(\d{1,2})\.(\d{1,2})', header_str)
                            if date_match:
                                day = int(date_match.group(1))
                                month = int(date_match.group(2))
                                
                                # Resolve year
                                # We assume the year is the true roster_date.year extracted from the "1 Apr 2025" header
                                year = roster_date.year if roster_date else datetime.now().year
                                
                                # Handle edge case where the grid starts late in the previous month (e.g. Dec 30th on a Jan roster)
                                if roster_date and roster_date.month == 1 and month == 12:
                                    year -= 1
                                # Handle edge cases where the grid bleeds into the next year (e.g. Jan 1st on a Dec roster)
                                elif roster_date and roster_date.month == 12 and month == 1:
                                    year += 1
                                    
                                try:
                                    mapped_date = datetime(year, month, day).date()
                                    header_dates[col_idx] = mapped_date
                                except ValueError:
                                    pass
                        continue
                        
                    # Need at least 4 columns to process data
                    if len(row) >= 4:
                        raw_name = str(row[0]).replace('\n', ' ').strip()
                        raw_emp_id = str(row[1]).strip()
                        
                        # Sometimes rows might visually exist but be empty
                        if not raw_emp_id or not raw_emp_id.isdigit():
                            continue
                            
                        # Determine which columns actually contain Dates to avoid parsing "Totals" columns
                        target_cols = [c for c in header_dates.keys() if c < len(row)]
                        if not target_cols:
                            # Fallback for Daily TO rosters where header parsing failed: Just use Column 3
                            target_cols = [3] if len(row) > 3 else []
                            
                        # Iterate horizontally over all date-validated duty columns
                        for col_idx in target_cols:
                            raw_duty_string = str(row[col_idx]).strip()
                            if not raw_duty_string or raw_duty_string.lower() in ['nan', 'none']:
                                continue
                                
                            # Determine the date for this specific cell
                            cell_date = header_dates.get(col_idx, roster_date)
                            
                            # Flatten vertical squished text 
                            flat_duty_string = raw_duty_string.replace('\n', '')
                            shift_start, shift_end = extract_shift_times(flat_duty_string)
                            
                            if shift_start and shift_end:
                                duty_code_only = re.sub(r'\(?\d{2}:\d{2}\s*-\s*\d{2}:\d{2}\)?', '', flat_duty_string).strip()
                            else:
                                first_line = raw_duty_string.split('\n')[0].strip()
                                if len(first_line) == 1 and '\n' in raw_duty_string:
                                    duty_code_only = flat_duty_string
                                else:
                                    duty_code_only = first_line
                                    
                            # Bifurcate Traffic Controllers into specific TC1 and TC2 roles while retaining the shift prefix (e.g. M-TC1)
                            if 'TC1' in duty_code_only or 'TC2' in duty_code_only:
                                match = re.search(r'([A-Za-z0-9\-]*?(?:TC1|TC2))', duty_code_only)
                                if match:
                                    duty_code_only = match.group(1)
                            
                            category, status = categorize_duty(raw_duty_string)
                            
                            # Resolve any composite crew_type for this specific employee
                            resolved_crew = resolve_crew_type(crew_type_global, raw_emp_id)

                            extracted_data.append({
                                'date': cell_date,
                                'name': raw_name,
                                'emp_id': raw_emp_id,
                                'duty_code_raw': duty_code_only,
                                'shift_start': shift_start,
                                'shift_end': shift_end,
                                'crew_type': resolved_crew,

                                # Processed columns appended immediately for downstream ease
                                'duty_category': category,
                                'status': status
                            })

    df = pd.DataFrame(extracted_data)
    return df

if __name__ == "__main__":
    # Test block
    print("Testing parser on local example...")
    df = parse_ivu_pdf('data/raw_pdfs/example_train_operator.pdf')
    print(f"Extracted {len(df)} records. Extracted Date: {df['date'].iloc[0] if not df.empty else 'Unknown'}, Crew Type: {df['crew_type'].iloc[0] if not df.empty else 'Unknown'}")
    print("\nSample records:")
    print(df[['date', 'name', 'emp_id', 'duty_code_raw', 'duty_category', 'shift_start']].head(10))
    print("\nValue Counts by Category:")
    print(df['duty_category'].value_counts())
