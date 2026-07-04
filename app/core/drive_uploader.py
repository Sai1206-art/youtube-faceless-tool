"""
Google Drive Uploader — Uploads the final video to a Drive folder
using a Google Service Account.
"""

import os
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from app.config import (
    GOOGLE_CREDENTIALS_JSON, DRIVE_FOLDER_ID,
)


class DriveUploader:
    SCOPES = ["https://www.googleapis.com/auth/drive.file"]

    def __init__(self):
        creds = service_account.Credentials.from_service_account_file(
            GOOGLE_CREDENTIALS_JSON, scopes=self.SCOPES
        )
        self.service = build("drive", "v3", credentials=creds)

    def upload_video(self, file_path: str, title: str = None) -> dict:
        """
        Upload a video file to Google Drive.

        Returns:
            dict with file_id, file_name, web_view_link, download_link
        """
        if title is None:
            title = os.path.basename(file_path)

        file_metadata = {
            "name": title,
        }
        if DRIVE_FOLDER_ID:
            file_metadata["parents"] = [DRIVE_FOLDER_ID]

        media = MediaFileUpload(
            file_path,
            mimetype="video/mp4",
            resumable=True,
        )

        file = self.service.files().create(
            body=file_metadata,
            media_body=media,
            fields="id, name, webViewLink, webContentLink",
        ).execute()

        return {
            "file_id": file.get("id"),
            "file_name": file.get("name"),
            "web_view_link": file.get("webViewLink"),
            "download_link": file.get("webContentLink"),
        }
