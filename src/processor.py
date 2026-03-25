import os
import pandas as pd
from datetime import datetime, timedelta, timezone
from src.drive_api import get_drive_service, get_all_pdfs_recursive, download_pdf
from src.pdf_parser import parse_ivu_pdf
from src.supabase_client import get_supabase_client, insert_raw_roster, insert_processed_roster, upsert_daily_summary, delete_records_for_date, get_sync_history, upsert_sync_history
from dotenv import load_dotenv

load_dotenv()

FOLDER_ID = os.environ.get('GOOGLE_DRIVE_FOLDER_ID')

def process_new_rosters(force_all=False):
    """
    Main pipeline function:
    1. Fetches new IVU PDFs from Google Drive
    2. Parses them into pandas DataFrame
    3. Transforms and calculates daily summary
    4. Uploads to Supabase
    """
    print("Starting roster processing pipeline...")
    
    # 1. Initialize Clients
    try:
        drive_service = get_drive_service()
        supabase_client = get_supabase_client()
    except Exception as e:
        msg = f"Error initializing services: {e}"
        print(msg)
        return {"status": "error", "message": msg}

    # 2. Fetch PDFs
    if not FOLDER_ID or FOLDER_ID == "your-folder-id":
        msg = "GOOGLE_DRIVE_FOLDER_ID is not configured. Aborting."
        print(msg)
        return {"status": "error", "message": msg}
        
    try:
        pdf_files = get_all_pdfs_recursive(drive_service, FOLDER_ID)
        print(f"Found {len(pdf_files)} PDF(s) recursively in Drive.")
    except Exception as e:
        msg = f"Error fetching from Drive: {e}"
        print(msg)
        return {"status": "error", "message": msg}

    # In a real environment, you'd want to track which files have already been processed
    # to avoid re-processing. For simplicity, we'll process the most recent one.
    if not pdf_files:
        msg = "No new rosters to process."
        print(msg)
        return {"status": "info", "message": msg}
        
    total_raw = 0
    total_processed = 0
    synced_dates = []
    
    # Fetch history of what we already synced
    try:
        sync_history = get_sync_history(supabase_client)
    except Exception as e:
        print(f"Error fetching sync history (first run?): {e}")
        sync_history = {}
        
    processed_count = 0
    
    threshold_time = datetime.now(timezone.utc) - timedelta(hours=8)
    
    for file in pdf_files:
        file_id = file['id']
        file_name = file['name']
        modified_time = file.get('modifiedTime', '')
        
        # 8-Hour Freshness Check
        if not force_all and modified_time:
            try:
                mod_dt = datetime.fromisoformat(modified_time.replace('Z', '+00:00'))
                if mod_dt < threshold_time:
                    # print(f"Skipping {file_name}: Modified older than 8 hours ({modified_time}).")
                    continue
            except ValueError:
                pass
                
        # Smart Skip Logic Avoids Redundant Work
        last_synced_modified = sync_history.get(file_id)
        if not force_all and last_synced_modified and modified_time and modified_time <= str(last_synced_modified):
            # print(f"Skipping {file_name}: Already up to date (Modified: {modified_time}).")
            continue
            
        print(f"Downloading {file_name} (New/Modified)...")
        local_pdf_path = download_pdf(drive_service, file_id, file_name)
        
        # 3. Parse PDF
        print(f"Parsing {file_name}...")
        try:
            df = parse_ivu_pdf(local_pdf_path, file_name=file_name)
            
            if df.empty:
                print(f"Warning: No data extracted from {file_name}. Skipping.")
                continue
                
            print(f"Successfully extracted {len(df)} records from {file_name}.")
            
            # Extract the actual computed date from the dataframe to use in the summary
            roster_date = df['date'].iloc[0]
        except Exception as e:
            print(f"Error parsing PDF {file_name}: {e}")
            continue

        # 4. Prepare data for Supabase
        # JSON requires python standard types. Convert date objects to strings safely
        if not pd.api.types.is_string_dtype(df['date']):
            df['date'] = df['date'].astype(str)
            
        # Deduplicate within this dataframe to avoid Postgres constraint conflicts
        # For raw_records
        raw_records = df[['date', 'name', 'emp_id', 'duty_code_raw', 'shift_start', 'shift_end', 'crew_type']].dropna(subset=['emp_id', 'duty_code_raw']).to_dict(orient='records')
        seen_raw = set()
        dedup_raw = []
        for r in raw_records:
            key = (r['date'], r['emp_id'])
            if key not in seen_raw:
                dedup_raw.append(r)
                seen_raw.add(key)
                
        # For processed_records
        processed_records = df[['date', 'emp_id', 'duty_category', 'duty_code_raw', 'status']].rename(columns={'duty_code_raw': 'duty_code'}).dropna(subset=['emp_id', 'duty_code']).to_dict(orient='records')
        seen_proc = set()
        dedup_proc = []
        for r in processed_records:
            key = (r['date'], r['emp_id'])
            if key not in seen_proc:
                dedup_proc.append(r)
                seen_proc.add(key)

        # 5. Insert into Supabase
        print(f"Uploading {file_name} to Supabase...")
        try:
            # Wipe existing records for this batch of employees on each date.
            # We delete by emp_id (not crew_type) so that historical crew_type renames
            # (e.g. "Crew Controller" → "Train Operators") don't leave stale orphan rows.
            unique_dates = df['date'].unique()
            for u_date in unique_dates:
                emp_ids_for_date = df[df['date'].astype(str) == str(u_date)]['emp_id'].unique().tolist()
                print(f"Clearing existing records for {len(emp_ids_for_date)} employees on {u_date}")
                delete_records_for_date(supabase_client, str(u_date), emp_ids=emp_ids_for_date)
                
                # Also clean processed_roster for the same employees on this date
                if emp_ids_for_date:
                    for i in range(0, len(emp_ids_for_date), 200):
                        chunk_ids = emp_ids_for_date[i:i+200]
                        try:
                            supabase_client.table('processed_roster').delete().eq('date', str(u_date)).in_('emp_id', chunk_ids).execute()
                        except Exception as e:
                            print(f"Warning cleaning processed_roster {u_date}: {e}")
            
            if dedup_raw:
                chunk_size = 1000
                for i in range(0, len(dedup_raw), chunk_size):
                    chunk = dedup_raw[i:i+chunk_size]
                    insert_raw_roster(supabase_client, chunk)
                print(f"Inserted {len(dedup_raw)} raw records.")
                total_raw += len(dedup_raw)
            
            if dedup_proc:
                chunk_size = 1000
                for i in range(0, len(dedup_proc), chunk_size):
                    chunk = dedup_proc[i:i+chunk_size]
                    insert_processed_roster(supabase_client, chunk)
                print(f"Inserted {len(dedup_proc)} processed records.")
                total_processed += len(dedup_proc)
            
            # Collect unique dates synced for reporting
            for u_date in df['date'].unique():
                if u_date not in synced_dates:
                    synced_dates.append(u_date)
            
            # Update sync history
            upsert_sync_history(supabase_client, file_id, file_name, modified_time)
            processed_count += 1
            
        except Exception as e:
            print(f"Error inserting {file_name} into Supabase: {e}")
            
    print("Pipeline execution complete.")
    
    if processed_count > 0:
        return {"status": "success", "message": f"Successfully processed {processed_count} files ({len(synced_dates)} dates). Inserted {total_raw} raw records."}
    else:
        return {"status": "info", "message": "All PDFs are already up to date. No new records synced."}


if __name__ == "__main__":
    process_new_rosters()
