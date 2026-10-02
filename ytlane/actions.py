"""
Built-in ytlane actions.

Each action wraps one step of the existing pipeline (app/core/*). Inputs that
an earlier action already produced are read from the lane context, so a lane
can be as short as:

    ctx.generate_script(prompt="...", images="photos/")
    ctx.voiceover()
    ctx.fetch_stock()
    ctx.compose_video()
    ctx.upload_youtube()

Heavy imports (openai, elevenlabs, google...) happen inside each action so
`ytlane lanes` / `ytlane actions` / `--dry-run` work without them installed.
"""

import os
import glob
import json
import subprocess
from typing import Optional

from ytlane.core import action, LaneError

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


# ─── Helpers ───────────────────────────────────────────────

def as_list(value) -> list[str]:
    """Accept a list, a comma-separated string, a directory or a glob."""
    if value is None:
        return []
    items = value if isinstance(value, (list, tuple)) else str(value).split(",")
    result = []
    for item in (str(i).strip() for i in items):
        if not item:
            continue
        if os.path.isdir(item):
            result += sorted(
                os.path.join(item, f) for f in os.listdir(item) if f.lower().endswith(IMAGE_EXTS)
            )
        elif any(ch in item for ch in "*?["):
            result += sorted(glob.glob(item))
        else:
            result.append(item)
    return result


def job_dir(ctx) -> str:
    if not ctx.workdir:
        from app.config import TEMP_DIR
        ctx.workdir = os.path.join(TEMP_DIR, ctx.job_id)
    os.makedirs(ctx.workdir, exist_ok=True)
    return ctx.workdir


def _read(path: str) -> Optional[str]:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    return None


# ─── Setup / utility actions ───────────────────────────────

@action(description="Fail fast if required environment variables are missing")
def ensure_env(ctx, keys):
    missing = [k for k in as_list(keys) if not os.getenv(k)]
    if missing:
        raise LaneError(f"Missing environment variables: {', '.join(missing)}")
    ctx.log(f"✓ env ok ({', '.join(as_list(keys))})")


@action(description="Run a shell command and return its stdout")
def sh(ctx, command, check=True):
    ctx.log(f"$ {command}")
    proc = subprocess.run(command, shell=True, capture_output=True, text=True)
    if proc.stdout:
        print(proc.stdout.rstrip())
    if check and proc.returncode != 0:
        raise LaneError(f"Command failed ({proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout


@action(description="Post a message to a Slack/Discord webhook (or just print it)")
def notify(ctx, message, webhook_url=None):
    url = webhook_url or os.getenv("YTLANE_WEBHOOK_URL")
    ctx.log(f"🔔 {message}")
    if url:
        import requests
        # "text" is read by Slack, "content" by Discord.
        requests.post(url, json={"text": message, "content": message}, timeout=10)


# ─── Script actions ────────────────────────────────────────

@action(description="Generate a structured video script with GPT-4o", output="script")
def generate_script(ctx, prompt, images=None, affiliate_link=None,
                    reference_video=None, extra_context=None):
    from app.core.script_generator import ScriptGenerator

    image_paths = as_list(images) or ctx.get("images", [])
    if not image_paths:
        raise LaneError("generate_script needs at least one product image (images=...)")
    ctx["images"] = image_paths
    script = ScriptGenerator().generate_script(
        prompt=prompt,
        product_images=image_paths,
        affiliate_link=affiliate_link,
        reference_video_path=reference_video,
        extra_context=extra_context,
    )
    ctx.log(f"✓ '{script['title']}' — {len(script['scenes'])} scenes")
    return script


@action(description="Save the current script to JSON (review/edit it before rendering)")
def save_script(ctx, path=None, script=None):
    script = ctx.require("script", script, "run generate_script or load_script first")
    path = path or os.path.join(job_dir(ctx), "script.json")
    payload = dict(script, _images=ctx.get("images", []))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    ctx.log(f"✓ script saved to {path}")
    return path


@action(description="Load a script JSON (skip the LLM call, re-render an edited script)", output="script")
def load_script(ctx, path):
    with open(path, encoding="utf-8") as f:
        script = json.load(f)
    images = script.pop("_images", None)
    if images and "images" not in ctx:
        ctx["images"] = images
    ctx.log(f"✓ loaded '{script.get('title')}' from {path}")
    return script


@action(description="Override title/description/tags from a metadata/ folder (like deliver)", output="metadata")
def load_metadata(ctx, path="metadata"):
    """Reads title.txt, description.txt, tags.txt (one per line or comma-separated)."""
    meta = {}
    title = _read(os.path.join(path, "title.txt"))
    description = _read(os.path.join(path, "description.txt"))
    tags = _read(os.path.join(path, "tags.txt"))
    if title:
        meta["title"] = title
    if description:
        meta["description"] = description
    if tags:
        meta["tags"] = [t.strip() for t in tags.replace("\n", ",").split(",") if t.strip()]

    if meta and "script" in ctx:
        ctx["script"].update(meta)
    ctx.log(f"✓ metadata: {', '.join(meta) or 'nothing found in ' + path}")
    return meta


# ─── Media actions ─────────────────────────────────────────

@action(description="Generate the voiceover with ElevenLabs", output="voiceover")
def voiceover(ctx, script=None):
    from app.core.tts_engine import TTSEngine

    script = ctx.require("script", script, "run generate_script first")
    result = TTSEngine().generate_voiceover(
        scenes=script["scenes"], output_dir=job_dir(ctx), job_id=ctx.job_id,
    )
    ctx.log(f"✓ voiceover {result['total_duration']:.1f}s")
    return result


@action(description="Pick product photos / download Pexels B-roll per scene", output="scene_assets")
def fetch_stock(ctx, script=None, images=None):
    from app.core.stock_footage import StockFootageFetcher

    script = ctx.require("script", script, "run generate_script first")
    image_paths = as_list(images) or ctx.get("images", [])
    stock = StockFootageFetcher()
    assets = []
    for i, scene in enumerate(script["scenes"]):
        asset = {"type": "fallback", "path": None}
        if scene.get("image_source") == "product":
            idx = scene.get("image_index", 0)
            if idx is not None and 0 <= idx < len(image_paths):
                asset = {"type": "product", "path": image_paths[idx]}
        elif scene.get("image_source") == "stock":
            path = stock.fetch_for_scene(
                visual_description=scene.get("visual_description", ""),
                scene_number=i, output_dir=job_dir(ctx), job_id=ctx.job_id,
            )
            if path:
                asset = {"type": "stock", "path": path}
        assets.append(asset)
    ctx.log(f"✓ {sum(a['type'] == 'stock' for a in assets)} stock clips")
    return assets


@action(description="Compose the final MP4 with ffmpeg", output="video_path")
def compose_video(ctx, script=None, music=None):
    from app.core.video_composer import VideoComposer

    script = ctx.require("script", script, "run generate_script first")
    tts = ctx.require("voiceover", hint="run voiceover first")
    assets = ctx.require("scene_assets", hint="run fetch_stock first")
    composer = VideoComposer()
    path = composer.compose_video(
        script=script,
        scene_durations=tts["scene_durations"],
        scene_assets=assets,
        voiceover_path=tts["full_audio_path"],
        job_id=ctx.job_id,
        background_music_path=music or composer._get_background_music(tts["scene_durations"]),
    )
    ctx.log(f"✓ video at {path}")
    return path


# ─── Upload actions ────────────────────────────────────────

@action(description="Upload the video to Google Drive", output="drive")
def upload_drive(ctx, video_path=None, title=None):
    from app.core.drive_uploader import DriveUploader

    video_path = ctx.require("video_path", video_path, "run compose_video first")
    title = title or f"{ctx.get('script', {}).get('title', ctx.job_id)}.mp4"
    result = DriveUploader().upload_video(file_path=video_path, title=title)
    ctx.log(f"✓ Drive: {result.get('web_view_link')}")
    return result


@action(description="Upload the video to YouTube (private by default)", output="youtube")
def upload_youtube(ctx, video_path=None, privacy="private", title=None,
                   description=None, tags=None, category=None):
    from app.core.youtube_uploader import YouTubeUploader

    if privacy not in ("private", "unlisted", "public"):
        raise LaneError("privacy must be private, unlisted or public")
    video_path = ctx.require("video_path", video_path, "run compose_video first")
    script = ctx.get("script", {})
    result = YouTubeUploader().upload_video(
        file_path=video_path,
        title=title or script.get("title", ctx.job_id),
        description=description or script.get("description", ""),
        tags=as_list(tags) or script.get("tags", []),
        category=category or script.get("category", "Science & Technology"),
        privacy_status=privacy,
    )
    ctx.log(f"✓ YouTube ({privacy}): {result.get('video_url')}")
    return result
