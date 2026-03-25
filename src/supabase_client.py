import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

def get_supabase_client() -> Client:
    """Returns an authenticated Supabase client."""
    if not SUPABASE_URL or not SUPABASE_KEY or SUPABASE_URL == "your-supabase-url-here" or SUPABASE_KEY == "your-supabase-anon-key-here":
        raise Exception("Supabase credentials not properly configured in .env file.")
        
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def insert_raw_roster(client: Client, data: list):
    """Inserts raw extracted data into Supabase."""
    if not data:
        return None
    response = client.table('raw_roster_data').insert(data).execute()
    return response

def insert_processed_roster(client: Client, data: list):
    """Inserts processed mapped data into Supabase."""
    if not data:
        return None
    response = client.table('processed_roster').insert(data).execute()
    return response

def upsert_daily_summary(client: Client, summary_data: dict):
    """Upserts the aggregated daily summary to Supabase."""
    # summary_data should be a dict like:
    # {"date": "2026-03-05", "on_duty_count": 50, "leave_count": 5...}
    response = client.table('daily_summary').upsert(summary_data).execute()
    return response

def fetch_all_by_date(client: Client, table: str, start_str: str, end_str: str, columns: str = '*') -> list:
    """Fetches all records for a date range, bypassing the 1000 row limit."""
    all_rows = []
    limit = 1000
    offset = 0
    while True:
        res = client.table(table).select(columns).gte('date', start_str).lte('date', end_str).range(offset, offset + limit - 1).execute()
        data = res.data
        if not data:
            break
        all_rows.extend(data)
        if len(data) < limit:
            break
        offset += limit
    return all_rows

def delete_records_for_date(client: Client, date_str: str, crew_type: str = None, emp_ids: list = None):
    """Safely deletes existing records for a specific date.
    
    Preferred strategy: delete by (date, emp_id) so that crew_type renames never cause
    stale rows to survive a re-sync.  The `crew_type` parameter is kept for backwards
    compatibility but is only used as a fallback when no emp_ids are provided.
    """
    try:
        if emp_ids:
            # Chunk to avoid URL length limits
            for i in range(0, len(emp_ids), 200):
                chunk = emp_ids[i:i+200]
                client.table('raw_roster_data').delete().eq('date', date_str).in_('emp_id', chunk).execute()
        elif crew_type:
            client.table('raw_roster_data').delete().eq('date', date_str).eq('crew_type', crew_type).execute()
    except Exception as e:
        print(f"Warning: Issue deleting old records (or none existed): {e}")

def get_sync_history(client: Client):
    """Fetches the history of synced files and their modification times."""
    res = client.table('sync_history').select('*').execute()
    return {row['file_id']: row['modified_time'] for row in res.data} if res.data else {}

def upsert_sync_history(client: Client, file_id: str, file_name: str, modified_time: str):
    """Records that a file has been successfully processed."""
    data = {
        'file_id': file_id,
        'file_name': file_name,
        'modified_time': modified_time
    }
    client.table('sync_history').upsert(data).execute()

if __name__ == "__main__":
    try:
        client = get_supabase_client()
        print("Successfully connected to Supabase!")
        # Test a simple query to ensure tables exist
        res = client.table('daily_summary').select('count', count='exact').limit(1).execute()
        print("Database schema appears accessible.")
    except Exception as e:
        print(f"Error testing Supabase connection: {e}")
