"""
Pipeline Orchestrator — The master controller that runs the entire workflow:
  1. Generate script (LLM)
  2. Generate voiceover (TTS)
  3. Fetch stock footage
  4. Compose video
  5. Upload to Drive
  6. Upload to YouTube as private (draft)
"""

import os
import uuid
import shutil
import traceback
from typing import Optional

from app.config import TEMP_DIR, OUTPUT_DIR
from app.core.script_generator import ScriptGenerator
from app.core.tts_engine import TTSEngine
from app.core.stock_footage import StockFootageFetcher
from app.core.video_composer import VideoComposer
from app.core.drive_uploader import DriveUploader
from app.core.youtube_uploader import YouTubeUploader


class Pipeline:
    def __init__(self):
        self.script_gen = ScriptGenerator()
        self.tts = TTSEngine()
        self.stock = StockFootageFetcher()
        self.composer = VideoComposer()

    def run(
        self,
        prompt: str,
        product_images: list[str],
        affiliate_link: Optional[str] = None,
        reference_video_path: Optional[str] = None,
        extra_context: Optional[str] = None,
        upload_to_drive: bool = True,
        upload_to_youtube: bool = True,
    ) -> dict:
        """
        Run the full video generation pipeline.

        Returns:
            dict with all results and metadata
        """
        job_id = f"job_{uuid.uuid4().hex[:8]}"
        job_temp = os.path.join(TEMP_DIR, job_id)
        os.makedirs(job_temp, exist_ok=True)

        result = {
            "job_id": job_id,
            "status": "running",
            "steps_completed": [],
        }

        try:
            # ═══════════════════════════════════════════════════════
            # STEP 1: Generate Script
            # ═══════════════════════════════════════════════════════
            print(f"[{job_id}] Step 1: Generating script with GPT-4o...")
            script = self.script_gen.generate_script(
                prompt=prompt,
                product_images=product_images,
                affiliate_link=affiliate_link,
                reference_video_path=reference_video_path,
                extra_context=extra_context,
            )
            result["script"] = script
            result["steps_completed"].append("script_generation")
            print(f"[{job_id}] ✓ Script generated: {script['title']}")
            print(f"[{job_id}]   Scenes: {len(script['scenes'])}")

            # ═══════════════════════════════════════════════════════
            # STEP 2: Generate Voiceover (TTS)
            # ═══════════════════════════════════════════════════════
            print(f"[{job_id}] Step 2: Generating voiceover with ElevenLabs...")
            tts_result = self.tts.generate_voiceover(
                scenes=script["scenes"],
                output_dir=job_temp,
                job_id=job_id,
            )
            result["voiceover"] = {
                "duration": round(tts_result["total_duration"], 1),
                "scene_durations": [round(d, 1) for d in tts_result["scene_durations"]],
            }
            result["steps_completed"].append("tts")
            print(f"[{job_id}] ✓ Voiceover generated: {tts_result['total_duration']:.1f}s")

            # ═══════════════════════════════════════════════════════
            # STEP 3: Fetch Stock Footage
            # ═══════════════════════════════════════════════════════
            print(f"[{job_id}] Step 3: Fetching stock footage...")
            scene_assets = []
            for i, scene in enumerate(script["scenes"]):
                asset = {"type": "fallback", "path": None}
                if scene.get("image_source") == "product":
                    img_idx = scene.get("image_index", 0)
                    if img_idx is not None and 0 <= img_idx < len(product_images):
                        asset = {"type": "product", "path": product_images[img_idx]}
                elif scene.get("image_source") == "stock":
                    path = self.stock.fetch_for_scene(
                        visual_description=scene.get("visual_description", ""),
                        scene_number=i,
                        output_dir=job_temp,
                        job_id=job_id,
                    )
                    if path:
                        asset = {"type": "stock", "path": path}
                scene_assets.append(asset)
            result["steps_completed"].append("stock_footage")
            stock_count = sum(1 for a in scene_assets if a["type"] == "stock")
            print(f"[{job_id}] ✓ Stock footage fetched for {stock_count} scenes")

            # ═══════════════════════════════════════════════════════
            # STEP 4: Compose Video
            # ═══════════════════════════════════════════════════════
            print(f"[{job_id}] Step 4: Composing video...")
            bg_music = self.composer._get_background_music(tts_result["scene_durations"])

            final_video_path = self.composer.compose_video(
                script=script,
                scene_durations=tts_result["scene_durations"],
                scene_assets=scene_assets,
                voiceover_path=tts_result["full_audio_path"],
                job_id=job_id,
                background_music_path=bg_music,
            )
            result["video_path"] = final_video_path
            result["steps_completed"].append("video_composition")
            print(f"[{job_id}] ✓ Video composed: {final_video_path}")

            # ═══════════════════════════════════════════════════════
            # STEP 5: Upload to Google Drive
            # ═══════════════════════════════════════════════════════
            if upload_to_drive and os.getenv("ENABLE_DRIVE_UPLOAD", "false").lower() == "true":
                print(f"[{job_id}] Step 5: Uploading to Google Drive...")
                try:
                    drive = DriveUploader()
                    drive_result = drive.upload_video(
                        file_path=final_video_path,
                        title=f"{script['title']}.mp4",
                    )
                    result["drive"] = drive_result
                    result["steps_completed"].append("drive_upload")
                    print(f"[{job_id}] ✓ Uploaded to Drive: {drive_result['web_view_link']}")
                except Exception as e:
                    print(f"[{job_id}] ⚠️ Drive upload skipped: {e}")
                    result["drive"] = {"error": str(e)}

            # ═══════════════════════════════════════════════════════
            # STEP 6: Upload to YouTube (as private/draft)
            # ═══════════════════════════════════════════════════════
            if upload_to_youtube and os.getenv("ENABLE_YOUTUBE_UPLOAD", "false").lower() == "true":
                print(f"[{job_id}] Step 6: Uploading to YouTube as private...")
                try:
                    yt = YouTubeUploader()
                    yt_result = yt.upload_video(
                        file_path=final_video_path,
                        title=script["title"],
                        description=script["description"],
                        tags=script.get("tags", []),
                        category=script.get("category", "Science & Technology"),
                        privacy_status="private",
                    )
                    result["youtube"] = yt_result
                    result["steps_completed"].append("youtube_upload")
                    print(f"[{job_id}] ✓ Uploaded to YouTube (private): {yt_result['video_url']}")
                except Exception as e:
                    print(f"[{job_id}] ⚠️ YouTube upload skipped: {e}")
                    result["youtube"] = {"error": str(e)}

            # ═══════════════════════════════════════════════════════
            # DONE
            # ═══════════════════════════════════════════════════════
            result["status"] = "completed"
            print(f"[{job_id}] ✅ Pipeline complete!")

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)
            result["traceback"] = traceback.format_exc()
            print(f"[{job_id}] ❌ Pipeline failed: {e}")
            print(traceback.format_exc())

        finally:
            # Cleanup temp files (keep final video)
            # Uncomment if you want to auto-clean temp files after each run
            # shutil.rmtree(job_temp, ignore_errors=True)
            pass

        return result
