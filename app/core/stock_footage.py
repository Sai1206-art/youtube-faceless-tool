"""
Stock Footage Fetcher — Fetches relevant B-roll from Pexels API
based on visual descriptions from the script.
"""

import os
import requests
from typing import Optional

from app.config import PEXELS_API_KEY, PEXELS_PER_PAGE, TEMP_DIR


class StockFootageFetcher:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({"Authorization": PEXELS_API_KEY})
        self.base_url = "https://api.pexels.com/v1"

    def search_video(self, query: str, per_page: int = PEXELS_PER_PAGE) -> list[dict]:
        """Search Pexels for videos matching the query."""
        url = f"{self.base_url}/videos/search"
        params = {
            "query": query,
            "per_page": per_page,
            "orientation": "landscape",
        }
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        return data.get("videos", [])

    def _pick_best_video(self, videos: list[dict]) -> Optional[dict]:
        """Pick the best video file from search results — prefer HD, reasonable duration."""
        if not videos:
            return None
        # Pick first video that has an HD file
        for video in videos:
            for video_file in video.get("video_files", []):
                if video_file.get("width", 0) >= 1920 and video_file.get("height", 0) >= 1080:
                    return video_file
        # Fallback: any file
        for video in videos:
            for video_file in video.get("video_files", []):
                if video_file.get("quality") == "hd":
                    return video_file
        return None

    def download_video(self, url: str, output_path: str) -> str:
        """Download a video file from Pexels."""
        resp = self.session.get(url, stream=True)
        resp.raise_for_status()
        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        return output_path

    def fetch_for_scene(
        self,
        visual_description: str,
        scene_number: int,
        output_dir: str = TEMP_DIR,
        job_id: str = "job",
    ) -> Optional[str]:
        """
        Fetch stock footage for a single scene.

        Returns:
            Path to downloaded video file, or None if nothing found.
        """
        # Try the full query first, then shorter keywords
        queries = [visual_description, " ".join(visual_description.split()[:3])]

        for query in queries:
            try:
                videos = self.search_video(query)
                best = self._pick_best_video(videos)
                if best:
                    path = os.path.join(output_dir, f"{job_id}_stock_{scene_number}.mp4")
                    self.download_video(best["link"], path)
                    return path
            except Exception as e:
                print(f"[StockFootage] Search failed for '{query}': {e}")
                continue

        # Final fallback: solid color clip (handled by video composer)
        return None
