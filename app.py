import streamlit as st

st.set_page_config(
    page_title="Staff Roster Analytics",
    page_icon=":material/train:",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Page definitions ──────────────────────────────────────────────────────────
daily_overview    = st.Page("pages/1_Daily_Overview.py",               title="Daily Overview",     icon="📊", default=True)
historical_trends = st.Page("pages/2_Historical_Trends.py",            title="Historical Trends",  icon="📈")
upload_roster     = st.Page("pages/8_Upload_Roster.py",                title="Upload Roster",      icon="📤")
admin_page        = st.Page("pages/9_Admin.py",                        title="Admin",              icon="⚙️")
fatigue_page      = st.Page("pages/6_Fatigue_fairness_management.py",  title="Fatigue Management", icon="⚖️")
raw_data_page     = st.Page("pages/5_Raw_Data_Explorer.py",            title="Raw Data Explorer",  icon="🗄️")
profile_page      = st.Page("pages/7_Employee_Profile.py",             title="Employee Profile",   icon="👤")

# ── All pages must be in the nav so their URLs work.
#    st.navigation() returns the currently selected page BEFORE running it,
#    so we can use it to decide which CSS to apply. ───────────────────────────
nav = st.navigation({
    "Analytics":   [daily_overview, historical_trends],
    "Admin Tools": [admin_page, fatigue_page, raw_data_page, profile_page, upload_roster],
})

# Detect if the currently selected page is one of the admin section pages
ADMIN_SECTION_TITLES = {"Admin", "Fatigue Management", "Raw Data Explorer", "Employee Profile"}
is_admin = nav.title in ADMIN_SECTION_TITLES

# ── CSS: hide/show based on which section is active ──────────────────────────
if is_admin:
    # Show Fatigue, Raw Data, Profile — but keep Admin link & Upload Roster hidden
    hide_css = """
    [data-testid="stSidebarNav"] li:has(a[href*="Admin"]) { display: none !important; }
    [data-testid="stSidebarNav"] li:has(a[href*="Upload_Roster"]) { display: none !important; }
    """
else:
    # Hide the ENTIRE "Admin Tools" section container (header + all links)
    hide_css = """
    [data-testid="stSidebarNavItems"] > div:has(li a[href*="Admin"]) { display: none !important; }
    [data-testid="stSidebarNavItems"] > div:has(li a[href*="Fatigue_fairness_management"]) { display: none !important; }
    [data-testid="stSidebarNavItems"] > div:has(li a[href*="Raw_Data_Explorer"]) { display: none !important; }
    [data-testid="stSidebarNavItems"] > div:has(li a[href*="Employee_Profile"]) { display: none !important; }
    [data-testid="stSidebarNavItems"] > div:has(li a[href*="Upload_Roster"]) { display: none !important; }
    """

st.markdown(f"<style>{hide_css}</style>", unsafe_allow_html=True)

nav.run()
