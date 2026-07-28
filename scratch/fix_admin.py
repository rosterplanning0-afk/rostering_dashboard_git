import os

path = r"c:\Users\BangeraP\Documents\my\my\py_pro\Deployed applications\rostering_dashboard\pages\9_Admin.py"
with open(path, "r", encoding="utf-8") as f:
    lines = f.readlines()

# The clean file starts at line 103 (index 102)
clean_lines = lines[102:]

with open(path, "w", encoding="utf-8") as f:
    f.writelines(clean_lines)
print("Fixed file.")
