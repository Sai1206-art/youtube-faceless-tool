"""
Stock Footage Fetcher — Fetches relevant B-roll from Pexels API
based on visual descriptions from the script.
"""

import os
import requests
from typing import Optional

from app.config import (
    PEXELS_API_KEY, PEXELS_PER_PAGE, BROLL_ORIENTATION, TEMP_DIR
)


class StockFootageFetcher:
    def __init__(self, orientation: str = BROLL_ORIENTATION):
        self.session = requests.Session()
        self.session.headers.update({"Authorization": PEXELS_API_KEY})
        self.base_url = "https://api.pexels.com/v1"
        self.orientation = orientation
        # Cache downloaded clips by query so repeated visual descriptions
        # (or the same B-roll across scenes) don't re-hit the API/network.
        self._cache: dict[str, str] = {}

    def search_video(self, query: str, per_page: int = PEXELS_PER_PAGE) -> list[dict]:
        """Search Pexels for videos matching the query."""
        url = f"{self.base_url}/videos/search"
        params = {
            "query": query,
            "per_page": per_page,
            "orientation": self.orientation,
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

    def _build_queries(self, visual_description: str, extra_keywords: Optional[str] = None) -> list[str]:
        """Build an ordered list of search queries, most specific first."""
        queries: list[str] = []
        vd = (visual_description or "").strip()
        if vd:
            queries.append(vd)
            words = vd.split()
            if len(words) > 3:
                queries.append(" ".join(words[:3]))
        if extra_keywords and extra_keywords.strip():
            queries.append(extra_keywords.strip())
        # De-duplicate while preserving order
        seen: set[str] = set()
        return [q for q in queries if not (q.lower() in seen or seen.add(q.lower()))]

    def fetch_for_scene(
        self,
        visual_description: str,
        scene_number: int,
        output_dir: str = TEMP_DIR,
        job_id: str = "job",
        extra_keywords: Optional[str] = None,
    ) -> Optional[str]:
        """
        Fetch stock footage (B-roll) for a single scene.

        Tries the full visual description first, then progressively broader
        keywords, and finally any provided fallback keywords (e.g. the video
        title/topic) so a scene rarely ends up with no relevant footage.

        Returns:
            Path to a downloaded video file, or None if nothing was found.
        """
        if not PEXELS_API_KEY:
            print("[StockFootage] PEXELS_API_KEY not set — skipping B-roll fetch.")
            return None

        for query in self._build_queries(visual_description, extra_keywords):
            # Reuse an already-downloaded clip for an identical query.
            cached = self._cache.get(query.lower())
            if cached and os.path.exists(cached):
                return cached
            try:
                videos = self.search_video(query)
                best = self._pick_best_video(videos)
                if best:
                    path = os.path.join(output_dir, f"{job_id}_stock_{scene_number}.mp4")
                    self.download_video(best["link"], path)
                    self._cache[query.lower()] = path
                    return path
            except Exception as e:
                print(f"[StockFootage] Search failed for '{query}': {e}")
                continue

        # Final fallback: solid color clip (handled by video composer)
        return None
