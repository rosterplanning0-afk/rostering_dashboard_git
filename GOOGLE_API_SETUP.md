# How to Create Google API Credentials for Drive and Sheets

To allow the dashboard to automatically download IVU roster PDFs from Google Drive and optionally write summaries to Google Sheets, you need a Service Account or OAuth credentials.
Using a **Service Account** is usually best for server-to-server or automated background tasks.

## Step-by-Step Guide (Service Account)

1. **Go to Google Cloud Console:**
   Navigate to [https://console.cloud.google.com/](https://console.cloud.google.com/) and sign in.

2. **Create a New Project:**
   - Click the project dropdown near the top-left and select **New Project**.
   - Name it (e.g., `Roster-Dashboard-App`), and click **Create**.

3. **Enable APIs:**
   - Ensure you have selected the newly created project.
   - Go to **APIs & Services > Library** via the left-hand navigation menu.
   - Search for **Google Drive API** and click **Enable**.
   - Search for **Google Sheets API** and click **Enable**.

4. **Create Credentials (Service Account):**
   - Go to **APIs & Services > Credentials**.
   - Click **+ CREATE CREDENTIALS** at the top and choose **Service account**.
   - Provide a Service account name (e.g., `roster-bot`) and click **Create and Continue**.
   - Grant it the role of `Editor` (or leave blank if it only needs access to specific files you share with it). Click **Continue**, then **Done**.

5. **Generate the Key (JSON Credentials File):**
   - In the **Credentials** page, click your newly created Service Account listed under "Service Accounts" (e.g., `roster-bot@...iam.gserviceaccount.com`).
   - Go to the **Keys** tab.
   - Click **Add Key > Create new key**.
   - Choose **JSON** and click **Create**.
   - A `.json` file will be downloaded to your computer.
   - **Important:** Keep this file secure! Rename it to `google_credentials.json` and place it in your project's root folder (`C:\Users\BangeraP\Documents\my\my\py_pro\rostering_dashbaord\`).
   - *Do not commit this file to public version control (it is excluded by `.gitignore` natively).*

6. **Share the Target Google Drive Folder:**
   - Go to your personal or organization's Google Drive.
   - Find the folder where the "IVU PDFs" are uploaded.
   - Right-click the folder -> **Share**.
   - Enter the **Email address of the Service Account** (you can find this email in the Google Cloud Console or inside the JSON file, under `client_email`) and give it **Viewer** or **Editor** permissions.
   - Once shared, the script can list and download files from that specific folder.
   
7. **Get the Folder ID:**
   - Open that shared folder in your browser.
   - Look at the URL: `https://drive.google.com/drive/folders/1ABC_XYZ123...`
   - The string of characters `1ABC_XYZ123...` is your **Folder ID**.
   - You will save this Folder ID in your `.env` file for the script to use.

## Environment variables setup

Create a `.env` file in the project directory looking like this:

```env
# Supabase details
SUPABASE_URL=your-supabase-url-here
SUPABASE_KEY=your-supabase-anon-key-here

# Google API details
GOOGLE_CREDENTIALS_PATH=google_credentials.json
GOOGLE_DRIVE_FOLDER_ID=your-folder-id-here
```
