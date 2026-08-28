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

    def search_video(
        self,
        query: str,
        per_page: int = PEXELS_PER_PAGE,
        orientation: str = "landscape",
    ) -> list[dict]:
        """Search Pexels for videos matching the query."""
        url = f"{self.base_url}/videos/search"
        params = {
            "query": query,
            "per_page": per_page,
            "orientation": orientation,
        }
        resp = self.session.get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        return data.get("videos", [])

    def _pick_best_video(self, videos: list[dict]) -> Optional[dict]:
        """Pick the best video file from search results — prefer HD (720p/1080p), reasonable duration."""
        if not videos:
            return None
        # Prefer 1280x720 or 1920x1080 (saves memory compared to 4K)
        for video in videos:
            for video_file in video.get("video_files", []):
                w = video_file.get("width", 0)
                h = video_file.get("height", 0)
                if 1280 <= w <= 1920 and 720 <= h <= 1080:
                    return video_file
        # Fallback to any HD file
        for video in videos:
            for video_file in video.get("video_files", []):
                if video_file.get("quality") == "hd":
                    return video_file
        # Second fallback: any file
        for video in videos:
            for video_file in video.get("video_files", []):
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

    def fetch_broll(
        self,
        query: str,
        index: int,
        output_dir: str = TEMP_DIR,
        job_id: str = "job",
        orientation: str = "landscape",
        used_video_ids: Optional[set] = None,
    ) -> Optional[dict]:
        """
        Fetch a single B-roll clip for an overlay insert.

        Unlike ``fetch_for_scene`` this avoids re-using the same Pexels video
        twice in one job (so consecutive inserts don't look identical) and
        returns the source clip's own duration so the composer knows whether
        it must loop the clip to fill the insert window.

        Args:
            query: Search phrase (a keyword/concept from the transcript).
            index: Insert index — used only for the output filename.
            orientation: "landscape" | "portrait" | "square".
            used_video_ids: Set of Pexels video ids already used this job;
                updated in place with the id that gets picked.

        Returns:
            {"path": str, "duration": float, "video_id": int} or None.
        """
        used_video_ids = used_video_ids if used_video_ids is not None else set()

        # Progressively broaden the query if the specific phrase finds nothing.
        words = query.split()
        queries = [query]
        if len(words) > 3:
            queries.append(" ".join(words[:3]))
        if len(words) > 1:
            queries.append(words[0])

        for q in queries:
            if not q.strip():
                continue
            try:
                videos = self.search_video(q, orientation=orientation)
            except Exception as e:
                print(f"[StockFootage] B-roll search failed for '{q}': {e}")
                continue

            # Prefer a video we haven't used yet in this job.
            ordered = [v for v in videos if v.get("id") not in used_video_ids] + [
                v for v in videos if v.get("id") in used_video_ids
            ]
            for video in ordered:
                best = self._pick_best_video([video])
                if not best:
                    continue
                path = os.path.join(output_dir, f"{job_id}_broll_{index}.mp4")
                try:
                    self.download_video(best["link"], path)
                except Exception as e:
                    print(f"[StockFootage] B-roll download failed for '{q}': {e}")
                    continue
                used_video_ids.add(video.get("id"))
                return {
                    "path": path,
                    "duration": float(video.get("duration", 0) or 0),
                    "video_id": video.get("id"),
                }

        return None
