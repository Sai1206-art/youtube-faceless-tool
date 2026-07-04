"""
Video Composer — Uses ffmpeg directly via subprocess for minimal memory usage.
This is critical for Render's free tier (512MB RAM).

Produces a 1280x720 (or 640x480) video with:
- Product images with text overlays
- Stock footage clips with text overlays
- Voiceover audio synced to scene durations
- Final concatenation via ffmpeg concat demuxer
"""

import os
import uuid
import subprocess
import textwrap
import json
from typing import Optional
from PIL import Image, ImageDraw, ImageFont

from app.config import (
    TEMP_DIR, OUTPUT_DIR, FPS, RESOLUTION, TARGET_DURATION, MAX_VIDEO_DURATION
)


class VideoComposer:
    def __init__(self):
        self.width, self.height = RESOLUTION

    def _get_ffmpeg(self):
        """Find the ffmpeg binary."""
        # Try imageio_ffmpeg first, then system ffmpeg
        try:
            import imageio_ffmpeg
            return imageio_ffmpeg.get_ffmpeg_exe()
        except Exception:
            return "ffmpeg"

    def _create_text_overlay(self, text: str, output_path: str) -> str:
        """Create a transparent PNG with stylized text overlay."""
        img = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        font = None
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/local/share/fonts/dejavu/DejaVuSans-Bold.ttf",
        ]
        for fp in font_paths:
            if os.path.exists(fp):
                try:
                    font = ImageFont.truetype(fp, 48)
                    break
                except Exception:
                    pass
        if not font:
            font = ImageFont.load_default()

        wrapped = textwrap.fill(text, width=35)
        bbox = draw.textbbox((0, 0), wrapped, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (self.width - text_w) // 2
        y = self.height - text_h - 80

        padding = 20
        bg_box = (x - padding, y - padding, x + text_w + padding, y + text_h + padding)
        draw.rounded_rectangle(bg_box, radius=15, fill=(0, 0, 0, 200))
        draw.text((x, y), wrapped, fill=(255, 255, 255, 255), font=font)

        img.save(output_path)
        return output_path

    def _make_image_segment(self, image_path: str, duration: float, text_overlay: Optional[str], output_path: str):
        """Create a video segment from a static image using ffmpeg."""
        ffmpeg = self._get_ffmpeg()

        # Prepare the image: resize to fit frame
        img = Image.open(image_path).convert("RGB")
        img_w, img_h = img.size
        scale = min(self.width / img_w, self.height / img_h)
        new_w, new_h = int(img_w * scale), int(img_h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)

        bg = Image.new("RGB", (self.width, self.height), (15, 15, 25))
        paste_x = (self.width - new_w) // 2
        paste_y = (self.height - new_h) // 2
        bg.paste(img, (paste_x, paste_y))

        prepared_path = output_path.replace(".mp4", "_prepared.png")
        bg.save(prepared_path)

        # Create text overlay if needed
        overlay_path = None
        if text_overlay:
            overlay_path = output_path.replace(".mp4", "_overlay.png")
            self._create_text_overlay(text_overlay, overlay_path)

        # Use ffmpeg to create video from image
        cmd = [
            ffmpeg, "-y",
            "-loop", "1", "-i", prepared_path,
            "-t", str(duration),
            "-r", str(FPS),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-preset", "veryfast",
        ]

        if overlay_path:
            cmd = [
                ffmpeg, "-y",
                "-loop", "1", "-i", prepared_path,
                "-loop", "1", "-i", overlay_path,
                "-t", str(duration),
                "-r", str(FPS),
                "-filter_complex", "[0:v][1:v]overlay=0:0",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "veryfast",
            ]

        cmd.extend(["-s", f"{self.width}x{self.height}", output_path])

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"[VideoComposer] ffmpeg image segment error: {result.stderr[-500:]}")
            # Fallback: create solid color segment
            self._make_color_segment(duration, text_overlay, output_path)

        # Cleanup temp images
        for p in [prepared_path, overlay_path]:
            if p and os.path.exists(p):
                os.remove(p)

    def _make_stock_segment(self, video_path: str, duration: float, text_overlay: Optional[str], output_path: str):
        """Create a video segment from stock footage using ffmpeg."""
        ffmpeg = self._get_ffmpeg()

        overlay_path = None
        if text_overlay:
            overlay_path = output_path.replace(".mp4", "_overlay.png")
            self._create_text_overlay(text_overlay, overlay_path)

        vf = f"scale={self.width}:{self.height}:force_original_aspect_ratio=decrease,pad={self.width}:{self.height}:(ow-iw)/2:(oh-ih)/2:color=0x0f0f19"

        if overlay_path:
            cmd = [
                ffmpeg, "-y",
                "-i", video_path,
                "-i", overlay_path,
                "-t", str(duration),
                "-r", str(FPS),
                "-filter_complex", f"[0:v]{vf}[bg];[bg][1:v]overlay=0:0",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "veryfast",
                "-an",
                output_path,
            ]
        else:
            cmd = [
                ffmpeg, "-y",
                "-i", video_path,
                "-t", str(duration),
                "-r", str(FPS),
                "-vf", vf,
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "veryfast",
                "-an",
                output_path,
            ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"[VideoComposer] ffmpeg stock segment error: {result.stderr[-500:]}")
            self._make_color_segment(duration, text_overlay, output_path)

        if overlay_path and os.path.exists(overlay_path):
            os.remove(overlay_path)

    def _make_color_segment(self, duration: float, text_overlay: Optional[str], output_path: str):
        """Create a solid color background segment using ffmpeg."""
        ffmpeg = self._get_ffmpeg()

        overlay_path = None
        if text_overlay:
            overlay_path = output_path.replace(".mp4", "_overlay.png")
            self._create_text_overlay(text_overlay, overlay_path)

        if overlay_path:
            cmd = [
                ffmpeg, "-y",
                "-f", "lavfi", "-i", f"color=c=0x0f0f19:s={self.width}x{self.height}:r={FPS}:d={duration}",
                "-i", overlay_path,
                "-filter_complex", "[0:v][1:v]overlay=0:0",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "veryfast",
                "-t", str(duration),
                output_path,
            ]
        else:
            cmd = [
                ffmpeg, "-y",
                "-f", "lavfi", "-i", f"color=c=0x0f0f19:s={self.width}x{self.height}:r={FPS}:d={duration}",
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "veryfast",
                "-t", str(duration),
                output_path,
            ]

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            print(f"[VideoComposer] ffmpeg color segment error: {result.stderr[-500:]}")

        if overlay_path and os.path.exists(overlay_path):
            os.remove(overlay_path)

    def _get_background_music(self, scene_durations: list[float]) -> Optional[str]:
        """Locate a royalty-free music file from the music/ directory."""
        music_dir = os.path.join(os.path.dirname(OUTPUT_DIR), "music")
        if not os.path.isdir(music_dir):
            return None
        for fname in os.listdir(music_dir):
            if fname.endswith((".mp3", ".wav", ".m4a")):
                return os.path.join(music_dir, fname)
        return None

    def compose_video(
        self,
        script: dict,
        scene_durations: list[float],
        scene_assets: list[dict],
        voiceover_path: str,
        job_id: str = "job",
        background_music_path: Optional[str] = None,
    ) -> str:
        """
        Compose the final video using ffmpeg subprocess calls.
        Each scene is processed individually, then concatenated.
        """
        scenes = script["scenes"]
        segment_paths = []
        job_temp = os.path.join(TEMP_DIR, f"{job_id}_segments")
        os.makedirs(job_temp, exist_ok=True)

        # ─── Create each scene segment ─────────────────────
        for i, scene in enumerate(scenes):
            duration = scene_durations[i]
            asset = scene_assets[i]
            segment_path = os.path.join(job_temp, f"scene_{i:03d}.mp4")
            text_overlay = scene.get("text_overlay", "")

            print(f"[VideoComposer] Scene {i+1}/{len(scenes)}: {asset['type']}, {duration:.1f}s")

            if asset["type"] == "product" and asset.get("path"):
                self._make_image_segment(asset["path"], duration, text_overlay, segment_path)
            elif asset["type"] == "stock" and asset.get("path"):
                self._make_stock_segment(asset["path"], duration, text_overlay, segment_path)
            else:
                self._make_color_segment(duration, text_overlay, segment_path)

            if os.path.exists(segment_path):
                segment_paths.append(segment_path)
            else:
                print(f"[VideoComposer] ⚠️ Scene {i+1} failed, creating fallback")
                self._make_color_segment(duration, text_overlay, segment_path)
                if os.path.exists(segment_path):
                    segment_paths.append(segment_path)

        # ─── Concatenate segments using ffmpeg concat ──────
        concat_list_path = os.path.join(job_temp, "concat_list.txt")
        with open(concat_list_path, "w") as f:
            for sp in segment_paths:
                f.write(f"file '{sp}'\n")

        video_no_audio_path = os.path.join(OUTPUT_DIR, f"{job_id}_video_only.mp4")
        ffmpeg = self._get_ffmpeg()

        concat_cmd = [
            ffmpeg, "-y",
            "-f", "concat", "-safe", "0",
            "-i", concat_list_path,
            "-c", "copy",
            video_no_audio_path,
        ]
        result = subprocess.run(concat_cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            # Fallback: re-encode
            print(f"[VideoComposer] concat copy failed, re-encoding...")
            concat_cmd = [
                ffmpeg, "-y",
                "-f", "concat", "-safe", "0",
                "-i", concat_list_path,
                "-c:v", "libx264",
                "-pix_fmt", "yuv420p",
                "-preset", "veryfast",
                video_no_audio_path,
            ]
            result = subprocess.run(concat_cmd, capture_output=True, text=True, timeout=120)

        # ─── Add voiceover audio ───────────────────────────
        output_path = os.path.join(OUTPUT_DIR, f"{job_id}_final.mp4")

        if background_music_path and os.path.exists(background_music_path):
            # Mix voiceover + background music
            mixed_audio_path = os.path.join(job_temp, "mixed_audio.mp3")
            mix_cmd = [
                ffmpeg, "-y",
                "-i", voiceover_path,
                "-i", background_music_path,
                "-filter_complex", "[0:a]volume=1.0[a1];[1:a]volume=0.15[a2];[a1][a2]amix=inputs=2:duration=first",
                "-c:a", "aac",
                mixed_audio_path,
            ]
            subprocess.run(mix_cmd, capture_output=True, text=True, timeout=60)
            audio_input = mixed_audio_path
        else:
            audio_input = voiceover_path

        final_cmd = [
            ffmpeg, "-y",
            "-i", video_no_audio_path,
            "-i", audio_input,
            "-c:v", "copy",
            "-c:a", "aac",
            "-shortest",
            output_path,
        ]
        result = subprocess.run(final_cmd, capture_output=True, text=True, timeout=120)
        if result.returncode != 0:
            print(f"[VideoComposer] Final mux error: {result.stderr[-500:]}")
            # If mux fails, at least return the video without audio
            if os.path.exists(video_no_audio_path):
                output_path = video_no_audio_path
            else:
                raise RuntimeError("Failed to compose final video")

        # ─── Cleanup temp files ────────────────────────────
        import shutil
        shutil.rmtree(job_temp, ignore_errors=True)
        if os.path.exists(video_no_audio_path) and video_no_audio_path != output_path:
            os.remove(video_no_audio_path)

        print(f"[VideoComposer] ✅ Video composed: {output_path}")
        return output_path
