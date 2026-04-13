import re

data = open('scratch_map.html', encoding='utf-8').read()

# Let's find any sequence of two large floats within brackets or near each other
# Typical coordinates for Ghaziabad/Delhi: lat ~ 28.6 to 29.0, lng ~ 77.1 to 77.8
matches = re.findall(r'(28\.\d{3,}).*?(77\.\d{3,})|(77\.\d{3,}).*?(28\.\d{3,})', data)

filtered = set()
for m in matches:
    if m[0]:  # (28, 77)
        filtered.add((m[0], m[1]))
    elif m[2]: # (77, 28)
        filtered.add((m[3], m[2]))

print(filtered)
