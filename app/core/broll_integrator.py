"""
B-roll Integrator — Takes an existing base video (typically a talking-head /
person-on-camera video) and automatically overlays relevant Pexels B-roll at
as many meaningful moments as possible, so the finished video stays visually
engaging while the speaker keeps talking.

Pipeline
--------
1. Probe the base video (dimensions, duration, audio presence).
2. Transcribe the speech with time-aligned segments (OpenAI Whisper).
3. Ask GPT-4o to turn the timed transcript into a *B-roll plan*: a list of
   time windows, each with a concrete visual search query and a layout that
   keeps the speaker on screen (picture-in-picture) or cuts away full-frame.
4. Fetch a distinct Pexels clip for every window.
5. Bake every clip onto the base video in one ffmpeg pass (BrollComposer).

Every step degrades gracefully: if transcription or the LLM planner is
unavailable, a heuristic planner still spreads B-roll across the timeline so
the caller always gets an enhanced video back.
"""

import os
import json
import uuid
from typing import Optional, Callable

from openai import OpenAI

from app.config import (
    OPENAI_API_KEY, TEMP_DIR, WHISPER_MODEL, BROLL_PLANNER_MODEL,
    BROLL_MIN_CLIP, BROLL_MAX_CLIP, BROLL_COVERAGE_TARGET,
    BROLL_DEFAULT_LAYOUT, BROLL_MAX_INSERTS, LLM_TEMPERATURE,
)
from app.core.stock_footage import StockFootageFetcher
from app.core.broll_composer import BrollComposer

# Corner rotation so consecutive PiP inserts don't stack in the same spot.
_PIP_ROTATION = ["pip_topright", "pip_topleft", "pip_bottomright", "pip_bottomleft"]


class BrollIntegrator:
    def __init__(self):
        self.client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
        self.stock = StockFootageFetcher()
        self.composer = BrollComposer()

    # ────────────────────────────────────────────────────────────
    # Step 1 — probe the base video
    # ────────────────────────────────────────────────────────────
    def probe_video(self, path: str) -> dict:
        """Return {width, height, duration, has_audio} using MoviePy."""
        from moviepy import VideoFileClip

        clip = VideoFileClip(path)
        try:
            w, h = clip.size
            info = {
                "width": int(w),
                "height": int(h),
                "duration": float(clip.duration or 0),
                "has_audio": clip.audio is not None,
            }
        finally:
            clip.close()
        return info

    def _extract_audio(self, video_path: str, out_dir: str, job_id: str) -> Optional[str]:
        """Extract a mono-ish audio track for transcription. None if silent."""
        from moviepy import VideoFileClip

        audio_path = os.path.join(out_dir, f"{job_id}_audio.mp3")
        clip = VideoFileClip(video_path)
        try:
            if clip.audio is None:
                return None
            clip.audio.write_audiofile(audio_path, logger=None)
        except Exception as e:
            print(f"[BrollIntegrator] Audio extraction failed: {e}")
            return None
        finally:
            clip.close()
        return audio_path if os.path.exists(audio_path) else None

    # ────────────────────────────────────────────────────────────
    # Step 2 — transcribe
    # ────────────────────────────────────────────────────────────
    def transcribe(self, audio_path: str) -> list[dict]:
        """
        Transcribe the audio into timed segments.

        Returns a list of {start, end, text}. Empty list if transcription is
        unavailable (no key / API error / silent track).
        """
        if not self.client or not audio_path:
            return []
        try:
            with open(audio_path, "rb") as f:
                resp = self.client.audio.transcriptions.create(
                    model=WHISPER_MODEL,
                    file=f,
                    response_format="verbose_json",
                    timestamp_granularities=["segment"],
                )
        except Exception as e:
            print(f"[BrollIntegrator] Transcription failed: {e}")
            return []

        segments = getattr(resp, "segments", None) or []
        out = []
        for s in segments:
            # SDK objects or dicts, depending on version.
            start = getattr(s, "start", None) if not isinstance(s, dict) else s.get("start")
            end = getattr(s, "end", None) if not isinstance(s, dict) else s.get("end")
            text = getattr(s, "text", None) if not isinstance(s, dict) else s.get("text")
            if start is None or end is None:
                continue
            out.append({"start": float(start), "end": float(end), "text": (text or "").strip()})
        return out

    # ────────────────────────────────────────────────────────────
    # Step 3 — plan the B-roll
    # ────────────────────────────────────────────────────────────
    def plan_broll(self, segments: list[dict], duration: float, extra_context: Optional[str] = None) -> list[dict]:
        """
        Produce a list of B-roll windows:
            {start, end, query, layout}
        Uses GPT-4o when possible; falls back to a heuristic planner.
        """
        plan = []
        if self.client and segments:
            plan = self._plan_with_llm(segments, duration, extra_context)
        if not plan:
            plan = self._plan_heuristic(segments, duration)
        return self._normalize_plan(plan, duration)

    def _plan_with_llm(self, segments: list[dict], duration: float, extra_context: Optional[str]) -> list[dict]:
        # Keep the transcript compact for the prompt.
        lines = [f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in segments if s["text"]]
        transcript = "\n".join(lines)[:12000]

        instruction = f"""You are a senior video editor cutting B-roll for a talking-head video.

Below is the time-aligned transcript of a {duration:.0f}-second video. For MAXIMUM
engagement, cover as much of the talking as possible with relevant B-roll — aim to
cover about {int(BROLL_COVERAGE_TARGET * 100)}% of the timeline. The speaker stays on
camera, so B-roll should mostly roll as a picture-in-picture inset ("pip_*"); use a
full-frame "fullscreen" cutaway only when the speaker names a concrete object/place/
scene that deserves the whole frame for a couple of seconds.

Return ONLY valid JSON in this exact shape (no markdown):
{{
  "inserts": [
    {{
      "start": 0.0,
      "end": 4.0,
      "query": "2-4 word Pexels video search for concrete, filmable visuals",
      "layout": "pip_topright" | "pip_topleft" | "pip_bottomright" | "pip_bottomleft" | "fullscreen"
    }}
  ]
}}

Rules:
- Each insert must be between {BROLL_MIN_CLIP:.0f} and {BROLL_MAX_CLIP:.0f} seconds long.
- Inserts must not overlap and must stay within 0..{duration:.1f} seconds.
- "query" must describe something a stock-footage site actually has (e.g.
  "city skyline aerial", "typing laptop closeup", "ocean waves"), NEVER abstract
  ideas or the literal words spoken.
- Prefer many short-to-medium inserts back-to-back over a few long ones.
- Rotate the pip corner between neighbours so they don't sit in the same place.
{f'- Creator note: {extra_context}' if extra_context else ''}

Transcript:
{transcript}
"""
        try:
            resp = self.client.chat.completions.create(
                model=BROLL_PLANNER_MODEL,
                messages=[{"role": "user", "content": instruction}],
                temperature=LLM_TEMPERATURE,
                response_format={"type": "json_object"},
            )
            data = json.loads(resp.choices[0].message.content)
            return data.get("inserts", []) or []
        except Exception as e:
            print(f"[BrollIntegrator] LLM planning failed: {e}")
            return []

    def _plan_heuristic(self, segments: list[dict], duration: float) -> list[dict]:
        """
        No-LLM fallback: derive a query from each transcript segment's own words
        (stripping filler) and rotate PiP corners. If there is no transcript at
        all, tile generic ambient B-roll across the whole duration.
        """
        stop = {
            "the", "a", "an", "and", "or", "but", "so", "to", "of", "in", "on",
            "for", "with", "this", "that", "is", "are", "was", "were", "it",
            "you", "your", "we", "i", "they", "he", "she", "as", "at", "by",
            "be", "have", "has", "will", "just", "really", "very", "like",
            "gonna", "going", "about", "into", "from", "my", "our", "their",
        }
        plan = []
        corner = 0

        if not segments:
            generic = ["technology abstract", "city timelapse", "nature landscape",
                       "business office", "data network", "light bokeh"]
            t = 0.0
            gi = 0
            while t < duration - 0.5:
                end = min(t + BROLL_MAX_CLIP, duration)
                plan.append({
                    "start": t, "end": end,
                    "query": generic[gi % len(generic)],
                    "layout": _PIP_ROTATION[corner % len(_PIP_ROTATION)],
                })
                t = end
                gi += 1
                corner += 1
            return plan

        for s in segments:
            words = [w.strip(".,!?—-:;\"'").lower() for w in s["text"].split()]
            keywords = [w for w in words if w and w not in stop and len(w) > 2]
            if not keywords:
                continue
            query = " ".join(keywords[:3])
            plan.append({
                "start": s["start"], "end": s["end"],
                "query": query,
                "layout": _PIP_ROTATION[corner % len(_PIP_ROTATION)],
            })
            corner += 1
        return plan

    def _normalize_plan(self, plan: list[dict], duration: float) -> list[dict]:
        """Clamp, clip-length-limit, split long windows, drop overlaps/tiny gaps."""
        clean = []
        for ins in plan:
            try:
                start = max(0.0, float(ins.get("start", 0)))
                end = min(float(duration), float(ins.get("end", 0)))
            except (TypeError, ValueError):
                continue
            query = str(ins.get("query", "")).strip()
            if not query or end - start < 0.4:
                continue
            layout = ins.get("layout") or BROLL_DEFAULT_LAYOUT
            clean.append({"start": start, "end": end, "query": query, "layout": layout})

        clean.sort(key=lambda x: x["start"])

        # Remove overlaps: trim each insert to start after the previous ends.
        deoverlapped = []
        last_end = 0.0
        for ins in clean:
            if ins["start"] < last_end:
                ins["start"] = last_end
            if ins["end"] - ins["start"] < BROLL_MIN_CLIP * 0.5:
                continue
            deoverlapped.append(ins)
            last_end = ins["end"]

        # Split windows longer than the max clip length into fresh cuts.
        final = []
        for ins in deoverlapped:
            span = ins["end"] - ins["start"]
            if span <= BROLL_MAX_CLIP:
                final.append(ins)
                continue
            t = ins["start"]
            piece = 0
            while t < ins["end"] - 0.1:
                seg_end = min(t + BROLL_MAX_CLIP, ins["end"])
                final.append({
                    "start": t, "end": seg_end,
                    "query": ins["query"],
                    # Rotate layout across the split pieces for variety.
                    "layout": _PIP_ROTATION[piece % len(_PIP_ROTATION)]
                    if ins["layout"] in _PIP_ROTATION else ins["layout"],
                })
                t = seg_end
                piece += 1

        return final[:BROLL_MAX_INSERTS]

    # ────────────────────────────────────────────────────────────
    # Full run
    # ────────────────────────────────────────────────────────────
    def run(
        self,
        base_video_path: str,
        job_id: Optional[str] = None,
        extra_context: Optional[str] = None,
        progress_callback: Optional[Callable] = None,
    ) -> dict:
        """
        Run the full B-roll integration and return a result dict with the
        final video path and the plan that was applied.
        """
        if not job_id:
            job_id = f"broll_{uuid.uuid4().hex[:8]}"
        job_temp = os.path.join(TEMP_DIR, job_id)
        os.makedirs(job_temp, exist_ok=True)

        result = {"job_id": job_id, "status": "running", "steps_completed": []}

        def report(step, status):
            if progress_callback:
                try:
                    progress_callback(job_id, step, status, result)
                except Exception as ex:
                    print(f"[{job_id}] progress callback error: {ex}")

        # 1) Probe
        report("probe", "running")
        info = self.probe_video(base_video_path)
        result["video_info"] = info
        result["steps_completed"].append("probe")
        report("probe", "completed")
        print(f"[{job_id}] Base video: {info['width']}x{info['height']}, "
              f"{info['duration']:.1f}s, audio={info['has_audio']}")

        # 2) Transcribe
        report("transcription", "running")
        audio_path = self._extract_audio(base_video_path, job_temp, job_id)
        segments = self.transcribe(audio_path) if audio_path else []
        result["transcript_segments"] = len(segments)
        result["steps_completed"].append("transcription")
        report("transcription", "completed")
        print(f"[{job_id}] Transcribed {len(segments)} speech segments")

        # 3) Plan
        report("planning", "running")
        plan = self.plan_broll(segments, info["duration"], extra_context)
        result["plan"] = plan
        result["steps_completed"].append("planning")
        report("planning", "completed")
        covered = sum(p["end"] - p["start"] for p in plan)
        coverage = (covered / info["duration"] * 100) if info["duration"] else 0
        result["coverage_percent"] = round(coverage, 1)
        print(f"[{job_id}] Planned {len(plan)} B-roll inserts "
              f"({coverage:.0f}% coverage)")

        # 4) Fetch clips
        report("fetch_broll", "running")
        orientation = "portrait" if info["height"] > info["width"] else "landscape"
        used_ids: set = set()
        inserts = []
        for i, p in enumerate(plan):
            clip = self.stock.fetch_broll(
                query=p["query"], index=i, output_dir=job_temp,
                job_id=job_id, orientation=orientation, used_video_ids=used_ids,
            )
            if clip:
                inserts.append({
                    "start": p["start"], "end": p["end"],
                    "clip_path": clip["path"], "clip_duration": clip["duration"],
                    "layout": p["layout"], "query": p["query"],
                })
            else:
                print(f"[{job_id}] No B-roll found for '{p['query']}' — skipping window")
        result["inserts_fetched"] = len(inserts)
        result["steps_completed"].append("fetch_broll")
        report("fetch_broll", "completed")
        print(f"[{job_id}] Fetched {len(inserts)}/{len(plan)} B-roll clips")

        # 5) Compose
        report("composition", "running")
        output_path = self.composer.compose(
            base_video_path=base_video_path,
            inserts=inserts,
            base_w=info["width"],
            base_h=info["height"],
            job_id=job_id,
        )
        result["video_path"] = output_path
        result["steps_completed"].append("composition")
        report("composition", "completed")

        result["status"] = "completed"
        report("done", "completed")
        print(f"[{job_id}] ✅ B-roll integration complete: {output_path}")
        return result
