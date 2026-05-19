import json
from src.supabase_client import get_supabase_client

def seed_counts():
    client = get_supabase_client()
    
    with open('config.json', 'r') as f:
        config = json.load(f)
        
    required_counts = config.get('required_counts', {})
    
    for role, data in required_counts.items():
        row = {
            'role': role,
            'effective_date': '2000-01-01', # Distant past so it acts as default for all history
            'shift_duty_required': data.get('shift_duty_required', {}),
            'total_shift_duty_required': data.get('total_shift_duty_required'),
            'maximum_leave_per_day': data.get('maximum_leave_per_day'),
            'ideal_weekly_off_per_day': data.get('ideal_weekly_off_per_day'),
            'general_shift_if_no_weekly_off': data.get('general_shift_if_no_weekly_off'),
            'total_count': data.get('total_count')
        }
        print(f"Upserting {role}...")
        client.table('role_required_counts').upsert(row).execute()
        
    print("Seeding completed.")

if __name__ == '__main__':
    seed_counts()
