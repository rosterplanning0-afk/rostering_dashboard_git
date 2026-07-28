import pandas as pd
import json
import os

# Paths
ROOT_DIR = r"c:\Users\BangeraP\Documents\my\my\py_pro\Deployed applications\rostering_dashboard"
CSV_PATH = os.path.join(ROOT_DIR, "categorized_duties.csv")
JSON_PATH = os.path.join(ROOT_DIR, "config.json")
OUTPUT_PATH = os.path.join(ROOT_DIR, "Duty_Codes_Export.xlsx")

def export_codes():
    data = []
    
    # 1. Read CSV exact matches
    if os.path.exists(CSV_PATH):
        df_csv = pd.read_csv(CSV_PATH)
        # Expected columns: 'Uncategorized list:' and 'categorized'
        cols = df_csv.columns.tolist()
        for _, row in df_csv.iterrows():
            code = str(row[cols[0]]).strip()
            cat = str(row[cols[1]]).strip()
            if code and cat and code.lower() != 'nan':
                data.append({
                    "Source": "CSV (Exact Match)",
                    "Code/Pattern": code,
                    "Category": cat
                })
                
    # 2. Read JSON Regex mapping
    if os.path.exists(JSON_PATH):
        with open(JSON_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
            mappings = config.get("duty_mapping", [])
            for mapping in mappings:
                data.append({
                    "Source": "Config (Regex Pattern)",
                    "Code/Pattern": mapping.get("pattern", ""),
                    "Category": mapping.get("category", "")
                })
                
    # Convert to DF and export
    df_export = pd.DataFrame(data)
    # Sort by category then code
    df_export = df_export.sort_values(by=["Category", "Code/Pattern"])
    
    # Use default engine
    df_export.to_excel(OUTPUT_PATH, index=False)
    print(f"Successfully exported {len(df_export)} mappings to {OUTPUT_PATH}")

if __name__ == "__main__":
    export_codes()
