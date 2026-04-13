import re
import requests
from urllib.parse import urlparse, parse_qs
from geopy.geocoders import ArcGIS

def get_arcgis_fallback(address: str):
    if not address or str(address).strip().lower() in ['nan', 'na', 'none', '']:
        return None, None
    try:
        geolocator = ArcGIS(timeout=10)
        loc = geolocator.geocode(address)
        if loc:
            return loc.latitude, loc.longitude
    except Exception as e:
        print(f"ArcGIS Error: {e}")
    return None, None
def extract_lat_lng(link: str):
    """
    Given a Google Maps URL, string, or short link, extracts the latitude and longitude.
    Returns a tuple (lat, lng) as floats, or (None, None) if not found.
    """
    if not link:
        return None, None
        
    session = requests.Session()
    # Mask as a real browser somewhat to avoid simple blocks
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'})
    
    try:
        r = session.get(link, allow_redirects=True, timeout=10)
        final_url = r.url
        html_content = r.text
        
        # 1. Check URL parameters for q=lat,lng
        parsed_url = urlparse(final_url)
        params = parse_qs(parsed_url.query)
        if 'q' in params:
            val = params['q'][0]
            val_match = re.match(r'(-?\d+\.\d+),(-?\d+\.\d+)', val)
            if val_match:
                return float(val_match.group(1)), float(val_match.group(2))
                
        # 2. Check URL for @lat,lng
        match = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', final_url)
        if match:
            return float(match.group(1)), float(match.group(2))
            
        # 3. Check URL for 3dlat!4dlng
        match = re.search(r'3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', final_url)
        if match:
            return float(match.group(1)), float(match.group(2))
            
        # 4. Check HTML for multiple numbers. The best matching coordinates in Ghaziabad/Delhi range.
        # We need to filter out the standard 'Google default' map center which is 28.672, 77.16864
        # which Google returns when it obfuscates the true coordinates via protobufs for dropped pins.
        matches = re.findall(r'(28\.\d{3,}).*?(77\.\d{3,})|(77\.\d{3,}).*?(28\.\d{3,})', html_content)
        for m in matches:
            lat = float(m[0] or m[3])
            lng = float(m[1] or m[2])
            # If it's not the exact default center of Google Maps for Delhi
            if not (abs(lat - 28.672) < 0.001 and abs(lng - 77.16864) < 0.001):
                return lat, lng
                
    except requests.RequestException as e:
        pass
        
    return None, None

if __name__ == "__main__":
    from src.supabase_client import get_supabase_client
    
    # We will temporarily disable RLS via Supabase MCP to make sure updates are saved,
    # but inside the app we'll assume it will either run with a service token or via a cron, 
    # or the user has RLS properly configured for their updates.
    
    client = get_supabase_client()
    print("Fetching employees without lat/lng but with geo_location_link...")
    
    res = client.table("employees").select("employee_id, geo_location_link, full_address, latitude").execute()
    data = res.data or []
    
    to_update = [emp for emp in data if (emp.get("geo_location_link") or emp.get("full_address")) and not emp.get("latitude")]
    print(f"Found {len(to_update)} employees to geocode.")
    
    updated_count = 0
    for i, emp in enumerate(to_update, 1):
        emp_id = emp['employee_id']
        link = emp.get('geo_location_link', '')
        address = emp.get('full_address', '')
        
        # If there are multiple links separated by spaces, take the first one
        if link:
            link = str(link).split()[0].split('2.https')[0] # Edge cases like 'link1 2.link2'
        
        print(f"[{i}/{len(to_update)}] ID {emp_id}: {address} | URL: {link} ...")
        
        lat, lng = extract_lat_lng(link)
        
        # Fallback to precise ArcGIS geocoding using the full address!
        if not lat or not lng:
            lat, lng = get_arcgis_fallback(address)
            if lat and lng:
                print(f"  -> Extracted via ArcGIS Address Fallback.")
        
        if lat and lng:
            try:
                res_update = client.table("employees").update({"latitude": lat, "longitude": lng}).eq("employee_id", emp_id).execute()
                if res_update.data:
                    print(f"  -> Success: {lat}, {lng}")
                    updated_count += 1
                else:
                    print("  -> Warning: Database update executed but returned no rows.")
            except Exception as e:
                print(f"  -> Database Error: {e}")
        else:
            print("  -> Failed to extract coordinates.")
            
    print(f"Process complete. Successfully geocoded and updated {updated_count} out of {len(to_update)} employees.")
