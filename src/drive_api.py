import os
import io
import json
import tempfile
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from dotenv import load_dotenv

load_dotenv()

SCOPES = ['https://www.googleapis.com/auth/drive.readonly']
UPLOAD_SCOPES = ['https://www.googleapis.com/auth/drive']


def get_google_credentials(scopes):
    """Retrieves Google service account credentials supporting Streamlit secrets, env vars, and local file."""
    # 1. Try Streamlit Secrets (if running in a Streamlit app)
    try:
        import streamlit as st
        # Requires Streamlit 1.28+ handling of secrets or standard dictionary-like access
        if "gcp_service_account" in st.secrets:
            creds_info = dict(st.secrets["gcp_service_account"])
            return service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)
    except Exception:
        pass

    # 2. Try JSON string from environment variable (Useful for Docker/CI)
    creds_json = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if creds_json:
        creds_info = json.loads(creds_json)
        return service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)

    # 3. Fallback to local JSON credentials file (Usually for local development)
    cred_path = os.environ.get('GOOGLE_CREDENTIALS_PATH', 'google_credentials.json').strip('"\'')
    if os.path.exists(cred_path):
        return service_account.Credentials.from_service_account_file(cred_path, scopes=scopes)
        
    # Extra fallback just in case the env var is messed up but the file is there
    if os.path.exists('google_credentials.json'):
        return service_account.Credentials.from_service_account_file('google_credentials.json', scopes=scopes)

    raise FileNotFoundError("Google API credentials not found in st.secrets, ENV, or local file.")

def get_google_drive_folder_id():
    """Retrieves the Google Drive Folder ID supporting Streamlit secrets and env vars."""
    try:
        import streamlit as st
        if "GOOGLE_DRIVE_FOLDER_ID" in st.secrets:
            return st.secrets["GOOGLE_DRIVE_FOLDER_ID"].strip('"\'')
    except Exception:
        pass
    
    val = os.environ.get('GOOGLE_DRIVE_FOLDER_ID')
    if val:
        return val.strip('"\'')
    return None


def get_drive_service():
    """Authenticates and returns the Google Drive API service (read-only)."""
    creds = get_google_credentials(SCOPES)
    service = build('drive', 'v3', credentials=creds)
    return service


def get_drive_upload_service():
    """Authenticates and returns the Google Drive API service with full read-write access."""
    creds = get_google_credentials(UPLOAD_SCOPES)
    service = build('drive', 'v3', credentials=creds)
    return service


def get_or_create_folder(service, parent_id, folder_name):
    """
    Returns the ID of a Drive folder with the given name inside parent_id.
    Creates the folder if it does not exist.
    """
    safe_name = folder_name.replace("'", "\\'")
    query = (
        f"'{parent_id}' in parents and "
        f"name = '{safe_name}' and "
        f"mimeType = 'application/vnd.google-apps.folder' and "
        f"trashed = false"
    )
    results = service.files().list(
        q=query,
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()

    folders = results.get('files', [])
    if folders:
        return folders[0]['id']

    metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder',
        'parents': [parent_id],
    }
    folder = service.files().create(
        body=metadata,
        fields='id',
        supportsAllDrives=True
    ).execute()
    return folder['id']


def upload_pdf_to_drive(service, file_bytes, file_name, parent_folder_id):
    """
    Uploads a PDF to the specified Drive folder.
    If a file with the same name already exists it is replaced (updated in-place,
    keeping the same file ID). Returns (file_id, was_replaced).
    """
    safe_name = file_name.replace("'", "\\'")
    query = (
        f"'{parent_folder_id}' in parents and "
        f"name = '{safe_name}' and "
        f"trashed = false"
    )
    results = service.files().list(
        q=query,
        fields="files(id, name)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()

    existing = results.get('files', [])
    media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype='application/pdf', resumable=True)

    if existing:
        file_id = existing[0]['id']
        updated = service.files().update(
            fileId=file_id,
            media_body=media,
            supportsAllDrives=True
        ).execute()
        return updated['id'], True  # True = file was replaced

    metadata = {
        'name': file_name,
        'parents': [parent_folder_id],
        'mimeType': 'application/pdf',
    }
    new_file = service.files().create(
        body=metadata,
        media_body=media,
        fields='id',
        supportsAllDrives=True
    ).execute()
    return new_file['id'], False  # False = new file created

def get_all_pdfs_recursive(service, folder_id):
    """Recursively fetches all PDFs from the specified Drive folder and its subfolders."""
    pdfs = []
    
    query = f"'{folder_id}' in parents and trashed=false"
    results = service.files().list(
        q=query,
        pageSize=1000,
        fields="nextPageToken, files(id, name, mimeType, modifiedTime)",
        supportsAllDrives=True,
        includeItemsFromAllDrives=True
    ).execute()
    
    items = results.get('files', [])
    for item in items:
        if item['mimeType'] == 'application/vnd.google-apps.folder':
            pdfs.extend(get_all_pdfs_recursive(service, item['id']))
        elif item['mimeType'] == 'application/pdf':
            pdfs.append(item)
            
    return pdfs

def download_pdf(service, file_id, file_name, download_dir='data/raw_pdfs'):
    """Downloads a file from Google Drive to a local directory."""
    if not os.path.exists(download_dir):
        os.makedirs(download_dir)
        
    request = service.files().get_media(fileId=file_id)
    file_path = os.path.join(download_dir, file_name)
    
    with open(file_path, 'wb') as f:
        downloader = MediaIoBaseDownload(f, request)
        done = False
        while done is False:
            status, done = downloader.next_chunk()
            # print(f"Download {int(status.progress() * 100)}%.")
            
    return file_path

if __name__ == "__main__":
    # Test the Drive connection
    try:
        service = get_drive_service()
        print("Successfully authenticated with Google Drive!")
        if FOLDER_ID and FOLDER_ID != "your-folder-id":
            files = get_all_pdfs_recursive(service, FOLDER_ID)
            print(f"Found {len(files)} PDFs recursively in folder {FOLDER_ID}")
            for f in files:
                print(f"- {f['name']} ({f.get('modifiedTime', 'N/A')})")
        else:
            print("Please set your GOOGLE_DRIVE_FOLDER_ID in the .env file.")
    except Exception as e:
        print(f"Error checking Google Drive API: {e}")
