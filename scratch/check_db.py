
import os
from supabase import create_client
from dotenv import load_dotenv

load_dotenv('.env')

url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

if not url or not key:
    print("Missing env vars")
    exit(1)

supabase = create_client(url, key)

try:
    res = supabase.table("employees").select("*").limit(1).execute()
    if res.data:
        print("Columns:", res.data[0].keys())
    
    res = supabase.table("employees").select("status").execute()
    statuses = set(row['status'] for row in res.data)
    print("Distinct Statuses:", statuses)
except Exception as e:
    print("Error:", e)
