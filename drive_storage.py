def refresh_folder_map():
    """Scan subfolders, generate folder_map.json, upload to Drive."""
    folder_id = os.getenv("GDRIVE_FOLDER_ID")
    service = get_drive_service()

    results = service.files().list(
        q=f"'{folder_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false",
        fields="files(id, name)"
    ).execute()

    folder_map = {f["name"].lower(): f["id"] for f in results.get("files", [])}

    # Upload as folder_map.json to the root or dedicated folder
    upload_json("folder_map.json", folder_map, folder_id=folder_id, service=service)

    return folder_map
    
def load_folder_map() -> Dict[str, str]:
    """Download folder_map.json from Drive and return as dict."""
    folder_id = os.getenv("GDRIVE_FOLDER_ID")
    service = get_drive_service()

    results = service.files().list(
        q=f"'{folder_id}' in parents and name = 'folder_map.json' and trashed = false",
        fields="files(id, name)",
        pageSize=1
    ).execute()

    files = results.get("files", [])
    if not files:
        raise FileNotFoundError("folder_map.json not found on Drive")

    file_id = files[0]["id"]
    return download_json(file_id, service=service)
