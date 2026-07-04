"""
Video Composer — Takes script + assets (product images, stock footage, TTS audio)
and composes the final video using MoviePy.

Produces a 1920x1080 video with:
- Ken Burns effect on product images (pan + zoom)
- Stock footage clips
- Text overlays per scene
- Voiceover audio synced to scene durations
- Background music (optional)
"""

import os
import textwrap
import numpy as np
from typing import Optional
from PIL import Image, ImageDraw, ImageFont
from moviepy import (
    ImageClip, VideoFileClip, AudioFileClip, concatenate_videoclips,
    CompositeVideoClip, ColorClip, TextClip, CompositeAudioClip
)

from app.config import (
    TEMP_DIR, OUTPUT_DIR, FPS, RESOLUTION, TARGET_DURATION, MAX_VIDEO_DURATION
)


class VideoComposer:
    def __init__(self):
        self.width, self.height = RESOLUTION

    def _create_text_image(self, text: str, font_size: int = 52) -> str:
        """Create a transparent PNG with stylized text overlay."""
        img = Image.new("RGBA", (self.width, self.height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)

        # Try to load a good font, fallback to default
        font = None
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
            "/Library/Fonts/Arial Bold.ttf",
            "C:\\Windows\\Fonts\\arialbd.ttf",
        ]
        for fp in font_paths:
            if os.path.exists(fp):
                font = ImageFont.truetype(fp, font_size)
                break
        if not font:
            font = ImageFont.load_default()

        # Wrap text
        wrapped = textwrap.fill(text, width=28)
        bbox = draw.textbbox((0, 0), wrapped, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        x = (self.width - text_w) // 2
        y = int(self.height * 0.75)  # lower third

        # Draw shadow + background pill
        padding = 20
        bg_box = (x - padding, y - padding, x + text_w + padding, y + text_h + padding)
        draw.rounded_rectangle(
            bg_box, radius=15, fill=(0, 0, 0, 200)
        )

        # Draw text
        draw.text((x, y), wrapped, fill=(255, 255, 255, 255), font=font)

        path = os.path.join(TEMP_DIR, f"text_overlay_{hash(text) & 0xFFFFFFFF}.png")
        img.save(path)
        return path

    def _make_product_clip(self, image_path: str, duration: float) -> ImageClip:
        """Create a Ken Burns effect clip from a product photo (slow pan + zoom)."""
        # Load and resize image to fit frame, maintaining aspect ratio
        img = Image.open(image_path).convert("RGB")
        img_w, img_h = img.size

        # Resize so image covers the full frame
        scale = max(self.width / img_w, self.height / img_h)
        new_w, new_h = int(img_w * scale), int(img_h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)
        img.save(os.path.join(TEMP_DIR, "_kb_temp.png"))

        # Ken Burns: subtle zoom + pan using VideoClip
        from moviepy import VideoClip
        zoom_factor = 1.08

        def make_frame(t):
            progress = t / duration if duration > 0 else 0
            current_zoom = 1 + (zoom_factor - 1) * progress
            # Pan from left-center to center
            pan_x = (new_w * current_zoom - self.width) * (0.5 - 0.3 * (1 - progress))
            pan_y = (new_h * current_zoom - self.height) / 2

            frame = np.array(img)
            # Crop based on zoom
            crop_w = int(self.width / current_zoom)
            crop_h = int(self.height / current_zoom)
            x_start = int(pan_x) if pan_x > 0 else 0
            y_start = int(pan_y) if pan_y > 0 else 0
            x_start = min(x_start, new_w - crop_w)
            y_start = min(y_start, new_h - crop_h)

            cropped = frame[y_start:y_start + crop_h, x_start:x_start + crop_w]
            # Resize back to full resolution
            pil = Image.fromarray(cropped).resize((self.width, self.height), Image.LANCZOS)
            return np.array(pil)

        clip = VideoClip(make_frame=make_frame, duration=duration).with_fps(FPS)
        return clip

    def _make_stock_clip(self, video_path: str, duration: float) -> VideoFileClip:
        """Create a clip from downloaded stock footage, trimmed and resized."""
        clip = VideoFileClip(video_path)
        # Trim to needed duration
        if clip.duration > duration:
            clip = clip.subclipped(0, duration)
        # Resize to fit frame
        clip = clip.resized((self.width, self.height))
        clip = clip.with_fps(FPS)
        return clip

    def _make_fallback_clip(self, duration: float, color=(15, 15, 25)) -> ColorClip:
        """Solid color background clip (fallback when no visuals available)."""
        return ColorClip(size=(self.width, self.height), color=color, duration=duration).with_fps(FPS)

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
        Compose the final video from all assets.

        Args:
            script: Full script dict from ScriptGenerator
            scene_durations: Actual audio durations per scene (from TTS)
            scene_assets: List of {"type": "product"|"stock"|"fallback", "path": str}
            voiceover_path: Path to full voiceover MP3
            job_id: Unique ID for naming output
            background_music_path: Optional path to music file

        Returns:
            Path to the final composed video file.
        """
        scenes = script["scenes"]
        video_clips = []

        for i, scene in enumerate(scenes):
            duration = scene_durations[i]
            asset = scene_assets[i]
            base_clip = None

            # ─── Create the visual clip ──────────────────────
            if asset["type"] == "product" and asset.get("path"):
                base_clip = self._make_product_clip(asset["path"], duration)
            elif asset["type"] == "stock" and asset.get("path"):
                try:
                    base_clip = self._make_stock_clip(asset["path"], duration)
                except Exception as e:
                    print(f"[Composer] Stock clip failed for scene {i}: {e}")
                    base_clip = self._make_fallback_clip(duration)
            else:
                base_clip = self._make_fallback_clip(duration)

            # ─── Add text overlay ────────────────────────────
            overlays = [base_clip]
            text_overlay = scene.get("text_overlay", "")
            if text_overlay:
                text_img_path = self._create_text_image(text_overlay)
                text_clip = ImageClip(text_img_path, duration=duration)
                overlays.append(text_clip)

            # ─── Combine visual + overlay ────────────────────
            scene_clip = CompositeVideoClip(overlays, size=(self.width, self.height))
            scene_clip = scene_clip.with_fps(FPS)
            video_clips.append(scene_clip)

        # ─── Concatenate all scenes ──────────────────────────
        final_video = concatenate_videoclips(video_clips, method="compose")

        # ─── Add voiceover audio ─────────────────────────────
        voiceover = AudioFileClip(voiceover_path)
        final_video = final_video.with_audio(voiceover)

        # ─── Add background music (optional) ─────────────────
        if background_music_path and os.path.exists(background_music_path):
            music = AudioFileClip(background_music_path)
            # Loop music if needed, trim to video duration
            if music.duration < final_video.duration:
                # Reuse the music file for simplicity
                pass
            music = music.subclipped(0, final_video.duration)
            # Lower music volume (30%)
            music = music.with_volume_scaled(0.15)
            # Mix voiceover + music
            mixed_audio = CompositeAudioClip([voiceover, music])
            final_video = final_video.with_audio(mixed_audio)

        # ─── Ensure we don't exceed max duration ─────────────
        if final_video.duration > MAX_VIDEO_DURATION:
            final_video = final_video.subclipped(0, MAX_VIDEO_DURATION)

        # ─── Write final video ───────────────────────────────
        output_path = os.path.join(OUTPUT_DIR, f"{job_id}_final.mp4")
        final_video.write_videofile(
            output_path,
            fps=FPS,
            codec="libx264",
            audio_codec="aac",
            preset="medium",
            threads=4,
            logger=None,
        )

        # ─── Cleanup ─────────────────────────────────────────
        for clip in video_clips:
            try:
                clip.close()
            except:
                pass
        voiceover.close()

        return output_path
