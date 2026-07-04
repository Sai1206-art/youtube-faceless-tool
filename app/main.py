"""
FastAPI Server — Web interface for the Faceless Tech Video Generator.

Endpoints:
  GET  /            → Web UI
  POST /api/generate → Run the pipeline in background (returns immediately)
  GET  /api/status/{job_id} → Get the real-time progress/status of a job
  GET  /api/health   → Health check
  GET  /api/download/{filename} → Download a generated video
"""

import os
import sys
import uuid
import shutil
import threading
from typing import Optional
from fastapi import FastAPI, File, UploadFile, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(title="Faceless Tech Video Generator", version="1.0.0")

# Global in-memory storage for jobs and their progress
jobs_db = {}

# Lazy load templates and config to catch import errors
try:
    from app.config import TEMP_DIR, OUTPUT_DIR, TEMPLATES_DIR, STATIC_DIR
    templates = Jinja2Templates(directory=TEMPLATES_DIR)
    if os.path.exists(STATIC_DIR):
        app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    print(f"✅ Config loaded: TEMP_DIR={TEMP_DIR}, OUTPUT_DIR={OUTPUT_DIR}")
except Exception as e:
    print(f"❌ Config import error: {e}")
    import traceback
    traceback.print_exc()
    TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
    templates = Jinja2Templates(directory=TEMPLATES_DIR)
    TEMP_DIR = "/tmp/faceless_temp"
    OUTPUT_DIR = "/tmp/faceless_output"
    os.makedirs(TEMP_DIR, exist_ok=True)
    os.makedirs(OUTPUT_DIR, exist_ok=True)


def run_pipeline_in_background(
    job_id: str,
    prompt: str,
    image_paths: list[str],
    affiliate_link: Optional[str],
    ref_video_path: Optional[str],
    extra_context: Optional[str],
    upload_dir: str,
):
    """Worker function running the pipeline in a background thread."""
    from app.core.pipeline import Pipeline

    # Define progress callback to sync background updates into jobs_db
    def progress_callback(jid, step, status, res):
        if jid not in jobs_db:
            jobs_db[jid] = {}

        jobs_db[jid]["current_step"] = step
        jobs_db[jid]["step_status"] = status

        # Sync result fields
        for key in ["status", "steps_completed", "script", "voiceover", "video_path", "drive", "youtube", "error"]:
            if key in res:
                jobs_db[jid][key] = res[key]

        # Generate download URL if video composed
        if res.get("video_path") and not jobs_db[jid].get("download_url"):
            filename = os.path.basename(res["video_path"])
            jobs_db[jid]["download_url"] = f"/api/download/{filename}"

    try:
        pipeline = Pipeline()
        pipeline.run(
            prompt=prompt,
            product_images=image_paths,
            affiliate_link=affiliate_link,
            reference_video_path=ref_video_path,
            extra_context=extra_context,
            upload_to_drive=False,
            upload_to_youtube=False,
            job_id=job_id,
            progress_callback=progress_callback,
        )
    except Exception as e:
        print(f"[{job_id}] Pipeline exception in background thread: {e}")
        if job_id not in jobs_db:
            jobs_db[job_id] = {}
        jobs_db[job_id]["status"] = "error"
        jobs_db[job_id]["error"] = str(e)
    finally:
        # Cleanup uploaded files directory
        shutil.rmtree(upload_dir, ignore_errors=True)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the main web UI."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "faceless-tech-video-generator"}


@app.get("/api/debug")
async def debug():
    """Debug endpoint to check what's installed and working."""
    import platform
    results = {
        "python": sys.version,
        "platform": platform.platform(),
        "active_jobs_count": len(jobs_db),
    }

    # Check imports
    checks = {}
    for mod in ["fastapi", "uvicorn", "openai", "elevenlabs", "pydub", "moviepy", "imageio_ffmpeg", "PIL", "numpy", "requests", "dotenv"]:
        try:
            m = __import__(mod)
            checks[mod] = f"✅ {getattr(m, '__version__', 'OK')}"
        except Exception as e:
            checks[mod] = f"❌ {e}"
    results["imports"] = checks

    # Check env vars
    results["env"] = {
        "OPENAI_API_KEY": "set" if os.getenv("OPENAI_API_KEY") else "missing",
        "ELEVENLABS_API_KEY": "set" if os.getenv("ELEVENLABS_API_KEY") else "missing",
        "PEXELS_API_KEY": "set" if os.getenv("PEXELS_API_KEY") else "missing",
        "PORT": os.getenv("PORT", "not set"),
    }

    return results


@app.post("/api/generate")
async def generate_video(
    prompt: str = Form(...),
    product_images: list[UploadFile] = File(...),
    affiliate_link: str = Form(""),
    extra_context: str = Form(""),
    reference_video: UploadFile = File(None),
):
    """
    Start video generation in a background thread to prevent blocking.
    """
    # Lazy import config and setup ffmpeg
    from app.config import _setup_ffmpeg, TEMP_DIR
    _setup_ffmpeg()

    # Create a unique job_id
    job_id = f"job_{uuid.uuid4().hex[:8]}"

    # Save uploaded files to temp folder for the background thread
    upload_dir = os.path.join(TEMP_DIR, f"upload_{job_id}")
    os.makedirs(upload_dir, exist_ok=True)

    image_paths = []
    for img in product_images:
        ext = os.path.splitext(img.filename)[1] or ".jpg"
        path = os.path.join(upload_dir, f"product_{len(image_paths)}{ext}")
        with open(path, "wb") as f:
            content = await img.read()
            f.write(content)
        image_paths.append(path)

    ref_video_path = None
    if reference_video and reference_video.filename:
        ext = os.path.splitext(reference_video.filename)[1] or ".mp4"
        ref_video_path = os.path.join(upload_dir, f"reference{ext}")
        with open(ref_video_path, "wb") as f:
            content = await reference_video.read()
            f.write(content)

    # Initialize state in global jobs_db
    jobs_db[job_id] = {
        "job_id": job_id,
        "status": "pending",
        "current_step": "script_generation",
        "step_status": "pending",
        "steps_completed": [],
    }

    # Start the worker thread
    t = threading.Thread(
        target=run_pipeline_in_background,
        kwargs={
            "job_id": job_id,
            "prompt": prompt,
            "image_paths": image_paths,
            "affiliate_link": affiliate_link or None,
            "ref_video_path": ref_video_path,
            "extra_context": extra_context or None,
            "upload_dir": upload_dir,
        }
    )
    t.daemon = True
    t.start()

    # Return immediately to avoid blocking uvicorn or Render
    return JSONResponse(content={
        "job_id": job_id,
        "status": "pending",
        "message": "Generation started in the background"
    })


@app.get("/api/status/{job_id}")
async def get_job_status(job_id: str):
    """Retrieve current progress of a background video generation job."""
    if job_id not in jobs_db:
        return JSONResponse(content={"error": "Job not found"}, status_code=404)
    return JSONResponse(content=jobs_db[job_id])


@app.get("/api/download/{filename}")
async def download_video(filename: str):
    """Download a generated video file."""
    from app.config import OUTPUT_DIR
    file_path = os.path.join(OUTPUT_DIR, filename)
    if not os.path.exists(file_path):
        return JSONResponse(content={"error": "File not found"}, status_code=404)
    return FileResponse(
        file_path,
        media_type="video/mp4",
        filename=filename,
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
