"""
TTS Engine — Generates voiceover audio using ElevenLabs.
Splits voiceover text by scene, generates audio per scene,
then concatenates into one continuous voiceover track.
"""

import os
from typing import Optional
from elevenlabs import ElevenLabs, save
from pydub import AudioSegment
from pydub.utils import mediainfo

from app.config import (
    ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID,
    TTS_MODEL, TTS_VOICE_SETTINGS, TEMP_DIR
)


class TTSEngine:
    def __init__(self):
        self.client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

    def _generate_scene_audio(self, text: str, output_path: str) -> str:
        """Generate TTS audio for a single scene's voiceover text."""
        audio = self.client.text_to_speech.convert(
            voice_id=ELEVENLABS_VOICE_ID,
            model_id=TTS_MODEL,
            text=text,
            voice_settings=TTS_VOICE_SETTINGS,
            output_format="mp3_44100_128",
        )
        save(audio, output_path)
        return output_path

    def generate_voiceover(
        self,
        scenes: list[dict],
        output_dir: str = TEMP_DIR,
        job_id: str = "job",
    ) -> dict:
        """
        Generate full voiceover from scene list.

        Args:
            scenes: List of scene dicts (must have 'voiceover' key)
            output_dir: Where to save audio files
            job_id: Unique identifier for naming files

        Returns:
            dict with:
              - full_audio_path: path to concatenated voiceover
              - scene_audio_paths: list of per-scene audio paths
              - scene_durations: list of actual audio durations in seconds
        """
        scene_audio_paths = []
        scene_durations = []

        for i, scene in enumerate(scenes):
            vo_text = scene.get("voiceover", "").strip()
            if not vo_text:
                # Empty voiceover — create silent audio matching scene duration
                duration = scene.get("duration_seconds", 3)
                silence = AudioSegment.silent(duration=duration * 1000)
                path = os.path.join(output_dir, f"{job_id}_scene_{i}.mp3")
                silence.export(path, format="mp3")
                scene_audio_paths.append(path)
                scene_durations.append(duration)
                continue

            path = os.path.join(output_dir, f"{job_id}_scene_{i}.mp3")
            self._generate_scene_audio(vo_text, path)
            scene_audio_paths.append(path)

            # Get actual duration
            info = mediainfo(path)
            duration = float(info["duration"])
            scene_durations.append(duration)

        # ─── Concatenate all scene audios ────────────────────
        combined = AudioSegment.empty()
        for path in scene_audio_paths:
            audio = AudioSegment.from_file(path)
            combined += audio

        full_path = os.path.join(output_dir, f"{job_id}_voiceover_full.mp3")
        combined.export(full_path, format="mp3")
        actual_total = len(combined) / 1000.0

        return {
            "full_audio_path": full_path,
            "scene_audio_paths": scene_audio_paths,
            "scene_durations": scene_durations,
            "total_duration": actual_total,
        }
