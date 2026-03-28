import os
import io
import json
import tempfile
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from dotenv import load_dotenv

load_dotenv()

# Use a single full scope so the stored OAuth token always covers both read and write.
# Narrower scopes like drive.readonly can cause 'invalid_scope' if the saved token
# was originally authorized with the full 'drive' scope (and vice-versa).
SCOPES = ['https://www.googleapis.com/auth/drive']
UPLOAD_SCOPES = SCOPES  # same scope for both operations


def _parse_creds(creds_info, scopes):
    """Detects and returns the correct credential object from dictionary info."""
    if "client_email" in creds_info and "private_key" in creds_info:
        from google.oauth2 import service_account
        return service_account.Credentials.from_service_account_info(creds_info, scopes=scopes)
    elif "refresh_token" in creds_info or "token" in creds_info:
        from google.oauth2.credentials import Credentials
        # For OAuth user tokens, do NOT pass 'scopes' — the token already
        # embeds the scopes it was authorized with. Passing a different set
        # causes Google to return 'invalid_scope: Bad Request'.
        return Credentials.from_authorized_user_info(creds_info)
    raise ValueError("Unrecognized credential format. Missing either 'client_email' (Service Account) or 'refresh_token' (OAuth).")

def _parse_file(filepath, scopes):
    """Detects and returns the correct credential object from a file."""
    with open(filepath, 'r') as f:
        creds_info = json.load(f)
    return _parse_creds(creds_info, scopes)

def get_google_credentials(scopes):
    """Retrieves Google API credentials supporting Streamlit secrets, env vars, and local files (OAuth or Service Account)."""
    
    # 1. Try Streamlit Secrets
    try:
        import streamlit as st
        # Option A: Dictionary style
        if "gcp_service_account" in st.secrets:
            return _parse_creds(dict(st.secrets["gcp_service_account"]), scopes)
            
        # Option B: Multi-line strings
        for secret_key in ["GOOGLE_OAUTH_TOKEN", "GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_CREDENTIALS_JSON"]:
            if secret_key in st.secrets:
                creds_info = json.loads(st.secrets[secret_key], strict=False)
                return _parse_creds(creds_info, scopes)
    except Exception as e:
        print(f"Failed to load from st.secrets: {e}")
        pass

    # 2. Try JSON strings from environment variables
    for env_key in ["GOOGLE_OAUTH_TOKEN", "GOOGLE_SERVICE_ACCOUNT_JSON", "GOOGLE_CREDENTIALS_JSON"]:
        env_val = os.environ.get(env_key)
        if env_val:
            try:
                creds_info = json.loads(env_val, strict=False)
                return _parse_creds(creds_info, scopes)
            except Exception:
                pass

    # 3. Try local files
    for path_key in ["GOOGLE_OAUTH_TOKEN_PATH", "GOOGLE_CREDENTIALS_PATH"]:
        cred_path = os.environ.get(path_key, '')
        if cred_path:
            cred_path = cred_path.strip('"\'')
            if os.path.exists(cred_path):
                return _parse_file(cred_path, scopes)
                
    # 4. Fallback default files
    for default_path in ['token.json', 'google_credentials.json']:
        if os.path.exists(default_path):
            return _parse_file(default_path, scopes)

    raise FileNotFoundError("Google API credentials not found in st.secrets, ENV, or standard local files.")

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
