"""
YouTube Uploader — Uploads the final video to YouTube as PRIVATE
(draft mode — stays unpublished until human review).

Uses the YouTube Data API v3 with a Google Service Account.
NOTE: YouTube API requires OAuth2 (user consent) for uploads —
service accounts don't work for YouTube uploads. Use the OAuth flow.
"""

import os
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from app.config import (
    GOOGLE_CREDENTIALS_JSON, YOUTUBE_CHANNEL_ID, TEMP_DIR,
)


class YouTubeUploader:
    SCOPES = [
        "https://www.googleapis.com/auth/youtube.upload",
        "https://www.googleapis.com/auth/youtube",
    ]

    def __init__(self):
        """Initialize YouTube uploader. Uses OAuth2 token (cached after first run)."""
        self.token_path = os.path.join(TEMP_DIR, "youtube_oauth_token.json")
        self.client_secrets_path = GOOGLE_CREDENTIALS_JSON
        self.service = self._get_service()

    def _get_service(self):
        """Handle OAuth2 authentication for YouTube."""
        creds = None

        # Load cached token if available
        if os.path.exists(self.token_path):
            creds = Credentials.from_authorized_user_file(self.token_path, self.SCOPES)

        # Refresh or get new token
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                # NOTE: This requires an OAuth client_secrets.json (NOT service account)
                # Download from Google Cloud Console > APIs & Services > Credentials
                # Create "OAuth client ID" > Desktop app
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.client_secrets_path, self.SCOPES
                )
                creds = flow.run_local_server(port=0)

            # Save token for future use
            with open(self.token_path, "w") as f:
                f.write(creds.to_json())

        return build("youtube", "v3", credentials=creds)

    def upload_video(
        self,
        file_path: str,
        title: str,
        description: str,
        tags: list[str],
        category: str = "Science & Technology",
        privacy_status: str = "private",  # private = draft
    ) -> dict:
        """
        Upload video to YouTube as private (draft).

        Args:
            file_path: Path to the MP4 file
            title: Video title
            description: Full description (with affiliate link if provided)
            tags: List of tags
            privacy_status: "private" (default), "unlisted", or "public"

        Returns:
            dict with video_id, video_url, privacy_status
        """
        # Category name → ID mapping
        category_map = {
            "Film & Animation": "1",
            "Autos & Vehicles": "2",
            "Music": "10",
            "Pets & Animals": "15",
            "Sports": "17",
            "Travel & Events": "19",
            "Gaming": "20",
            "People & Blogs": "22",
            "Comedy": "23",
            "Entertainment": "24",
            "News & Politics": "25",
            "Howto & Style": "26",
            "Education": "27",
            "Science & Technology": "28",
            "Nonprofits & Activism": "29",
        }
        category_id = category_map.get(category, "28")  # Default: Sci & Tech

        body = {
            "snippet": {
                "title": title[:100],  # YouTube max 100 chars
                "description": description[:5000],
                "tags": tags[:500],
                "categoryId": category_id,
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False,
                "containsSyntheticMedia": True,  # Mark as AI-generated
            },
        }

        media = MediaFileUpload(file_path, mimetype="video/mp4", resumable=True)

        request = self.service.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            status, response = request.next_chunk()
            if status:
                print(f"[YouTube] Upload progress: {int(status.progress() * 100)}%")

        return {
            "video_id": response.get("id"),
            "video_url": f"https://www.youtube.com/watch?v={response.get('id')}",
            "privacy_status": privacy_status,
            "title": title,
            "description_preview": description[:200],
        }
