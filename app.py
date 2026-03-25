import streamlit as st

st.set_page_config(
    page_title="Staff Roster Analytics",
    page_icon=":material/train:",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Define pages (hiding the old app.py splash screen content)
daily_overview = st.Page("pages/1_Daily_Overview.py", title="Daily Overview", icon="📊", default=True)
historical_trends = st.Page("pages/4_Historical_Trends.py", title="Historical Trends", icon="📈")
raw_data = st.Page("pages/5_Raw_Data_Explorer.py", title="Raw Data Explorer", icon="🗄️")
fatigue = st.Page("pages/6_Fatigue_fairness_management.py", title="Fatigue Management", icon="⚖️")
profile = st.Page("pages/7_Employee_Profile.py", title="Employee Profile", icon="👤")
upload_roster = st.Page("pages/8_Upload_Roster.py", title="Upload Roster", icon="📤")

pg = st.navigation({
    "Analytics": [daily_overview, historical_trends],
    "Tools": [fatigue, profile, raw_data, upload_roster]
})

pg.run()
