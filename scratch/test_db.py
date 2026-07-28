import os
from dotenv import load_dotenv
load_dotenv()
from src.supabase_client import get_supabase_client
print("URL:", os.environ.get("SUPABASE_URL"))
client = get_supabase_client()
res1 = client.table('raw_roster_data').select('count', count='exact').limit(1).execute()
res2 = client.table('processed_roster').select('count', count='exact').limit(1).execute()
print(f"Raw count: {res1.count}")
print(f"Processed count: {res2.count}")
