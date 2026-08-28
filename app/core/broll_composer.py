"""
B-roll Composer — Overlays fetched Pexels B-roll clips onto an existing
base (talking-head) video using a single ffmpeg ``filter_complex`` pass.

Design goals
------------
* Keep the base video's own audio (the speaker) untouched.
* Support two families of layout so the request "the person while talking
  should have B-roll rolling as well" is satisfied by default:
    - Picture-in-picture ("pip_*")  → speaker stays full-frame, B-roll rolls
      in a large rounded inset in a corner. This is the default.
    - Full-frame cutaway ("fullscreen") → B-roll fills the frame while the
      speaker keeps talking underneath (audio only).
* Time-gate every overlay with ``enable='between(t,start,end)'`` so all
  inserts are baked in one encode instead of N re-encodes.

Each insert is a dict:
    {
      "start": float,        # seconds into the base video
      "end": float,          # seconds into the base video
      "clip_path": str,      # local mp4 fetched from Pexels
      "clip_duration": float,# source clip length (0 = unknown → assume loops)
      "layout": str,         # pip_topright | pip_topleft | pip_bottomright
                             # | pip_bottomleft | fullscreen
    }
"""

import os
import subprocess
from typing import Optional

from app.config import (
    OUTPUT_DIR, FPS, BROLL_PIP_SCALE, BROLL_PIP_MARGIN, BROLL_DEFAULT_LAYOUT,
)

# Layouts that keep the speaker visible (inset) vs. cover the whole frame.
_PIP_LAYOUTS = {"pip_topright", "pip_topleft", "pip_bottomright", "pip_bottomleft"}


class BrollComposer:
    def __init__(self):
        pass

    def _get_ffmpeg(self):
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return "ffmpeg"

    def _inset_geometry(self, layout: str, base_w: int, base_h: int):
        """Return (inset_w, inset_h, x_expr, y_expr) for a PiP layout."""
        inset_w = int(base_w * BROLL_PIP_SCALE)
        inset_h = int(base_h * BROLL_PIP_SCALE)
        # Keep even dimensions (yuv420p requirement).
        inset_w -= inset_w % 2
        inset_h -= inset_h % 2
        m = BROLL_PIP_MARGIN

        if layout == "pip_topleft":
            x, y = m, m
        elif layout == "pip_bottomright":
            x, y = base_w - inset_w - m, base_h - inset_h - m
        elif layout == "pip_bottomleft":
            x, y = m, base_h - inset_h - m
        else:  # pip_topright (default)
            x, y = base_w - inset_w - m, m
        return inset_w, inset_h, x, y

    def compose(
        self,
        base_video_path: str,
        inserts: list[dict],
        base_w: int,
        base_h: int,
        job_id: str = "job",
        output_path: Optional[str] = None,
    ) -> str:
        """
        Bake all B-roll inserts onto the base video.

        Returns the path to the rendered mp4. If there are no inserts (or the
        filtered render fails), the base video is copied through unchanged so
        the caller always gets a valid file back.
        """
        ffmpeg = self._get_ffmpeg()
        if output_path is None:
            output_path = os.path.join(OUTPUT_DIR, f"{job_id}_broll.mp4")

        # Even dimensions are required by yuv420p / libx264.
        base_w -= base_w % 2
        base_h -= base_h % 2

        valid = [
            ins for ins in inserts
            if ins.get("clip_path") and os.path.exists(ins["clip_path"])
            and ins.get("end", 0) > ins.get("start", 0)
        ]

        if not valid:
            print("[BrollComposer] No usable inserts — passing base video through.")
            return self._passthrough(base_video_path, output_path)

        # ─── Build ffmpeg inputs ───────────────────────────────
        # Input 0 is the base video. Each insert is a looped input trimmed to
        # its window length so short clips fill long windows.
        cmd = [ffmpeg, "-y", "-i", base_video_path]
        for ins in valid:
            window = max(0.1, ins["end"] - ins["start"])
            # Loop the source clip if it is shorter than the window (or unknown).
            cmd += ["-stream_loop", "-1", "-t", f"{window:.3f}", "-i", ins["clip_path"]]

        # ─── Build the filter graph ────────────────────────────
        filters = []
        # Normalise the base to an even-sized, fixed-fps canvas.
        filters.append(
            f"[0:v]scale={base_w}:{base_h}:force_original_aspect_ratio=decrease,"
            f"pad={base_w}:{base_h}:(ow-iw)/2:(oh-ih)/2:color=black,"
            f"setsar=1,fps={FPS}[base]"
        )

        prev = "base"
        for i, ins in enumerate(valid):
            in_idx = i + 1  # ffmpeg input index (0 is base)
            layout = ins.get("layout") or BROLL_DEFAULT_LAYOUT
            start = ins["start"]
            end = ins["end"]

            if layout in _PIP_LAYOUTS:
                iw, ih, x, y = self._inset_geometry(layout, base_w, base_h)
                # Scale-to-fill the inset box then crop the overflow, add a
                # thin border so the inset reads as an intentional element.
                filters.append(
                    f"[{in_idx}:v]setpts=PTS-STARTPTS,"
                    f"scale={iw}:{ih}:force_original_aspect_ratio=increase,"
                    f"crop={iw}:{ih},setsar=1,fps={FPS},"
                    f"pad={iw + 6}:{ih + 6}:3:3:color=white[bz{i}]"
                )
                ox, oy = x - 3, y - 3
                filters.append(
                    f"[{prev}][bz{i}]overlay={ox}:{oy}:"
                    f"enable='between(t,{start:.3f},{end:.3f})'[v{i}]"
                )
            else:  # fullscreen cutaway
                filters.append(
                    f"[{in_idx}:v]setpts=PTS-STARTPTS,"
                    f"scale={base_w}:{base_h}:force_original_aspect_ratio=increase,"
                    f"crop={base_w}:{base_h},setsar=1,fps={FPS}[bz{i}]"
                )
                filters.append(
                    f"[{prev}][bz{i}]overlay=0:0:"
                    f"enable='between(t,{start:.3f},{end:.3f})'[v{i}]"
                )
            prev = f"v{i}"

        filter_complex = ";".join(filters)

        cmd += [
            "-filter_complex", filter_complex,
            "-map", f"[{prev}]",
            "-map", "0:a?",           # keep the speaker's original audio
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "veryfast",
            "-crf", "23",
            "-c:a", "aac",
            "-shortest",
            output_path,
        ]

        print(f"[BrollComposer] Rendering {len(valid)} B-roll inserts onto base video...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1800)
        if result.returncode != 0 or not os.path.exists(output_path):
            print(f"[BrollComposer] filter render failed: {result.stderr[-800:]}")
            return self._passthrough(base_video_path, output_path)

        print(f"[BrollComposer] ✅ B-roll video composed: {output_path}")
        return output_path

    def _passthrough(self, base_video_path: str, output_path: str) -> str:
        """Re-encode the base video unchanged as a safe fallback."""
        ffmpeg = self._get_ffmpeg()
        cmd = [
            ffmpeg, "-y", "-i", base_video_path,
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "veryfast",
            "-c:a", "aac", output_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            # Last resort: stream copy.
            subprocess.run(
                [ffmpeg, "-y", "-i", base_video_path, "-c", "copy", output_path],
                capture_output=True, text=True, timeout=300,
            )
        return output_path
