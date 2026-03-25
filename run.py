import subprocess
import os
import sys

def main():
    # print("Starting Staff Roster Analytics System...")
    
    # # 1. Run the background processor to fetch new PDFs if available
    # print("\n[1/2] Checking for new Google Drive rosters and running DB sync...")
    # try:
    #     subprocess.run([sys.executable, "-m", "src.processor"], check=False)
    # except Exception as e:
    #     print(f"Error running processor: {e}")
        
    # 2. Start the Streamlit Dashboard
    print("\n[2/2] Booting up Dashboard UI...")
    try:
        # We use os.system here so the streamlit server runs in the foreground
        os.system("streamlit run app.py")
    except Exception as e:
        print(f"Error starting Streamlit: {e}")

if __name__ == "__main__":
    main()
