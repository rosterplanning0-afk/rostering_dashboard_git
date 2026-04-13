import requests
import re
from urllib.parse import urlparse, parse_qs

urls = [
    'https://maps.app.goo.gl/9YvnZ7T4835MqgXf6',
    'https://goo.gl/maps/JDnt2Q558ME2LtLk7?g_st=ac'
]

for url in urls:
    r = requests.get(url, allow_redirects=True)
    final_url = r.url
    print("URL:", final_url)
    
    # Try parsing meta tags
    match = re.search(r'meta content="https://maps\.google\.com/maps/api/staticmap\?center=(-?\d+\.\d+)%2C(-?\d+\.\d+)', r.text)
    if match:
        print("Meta Match:", match.groups())
    
    # Try parsing init data
    match2 = re.search(r'APP_INITIALIZATION_STATE=\[\[\[(?:[-\d.]+,){2}([-\d.]+),([-\d.]+)', r.text)
    if match2:
        print("Init Match:", match2.groups())
    
    match3 = re.search(r'@(-?\d+\.\d+),(-?\d+\.\d+)', final_url)
    if match3:
        print("URL @ Match:", match3.groups())
        
    match4 = re.search(r'3d(-?\d+\.\d+)!4d(-?\d+\.\d+)', final_url)
    if match4:
        print("URL 3d4d Match:", match4.groups())
