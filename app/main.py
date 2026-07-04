"""
FastAPI Server — Web interface for the Faceless Tech Video Generator.

Endpoints:
  GET  /            → Web UI
  POST /api/generate → Run the pipeline (multipart form upload)
  GET  /api/health   → Health check
  GET  /api/download/{filename} → Download a generated video
"""

import os
import uuid
import shutil
from fastapi import FastAPI, File, UploadFile, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import TEMP_DIR, OUTPUT_DIR, TEMPLATES_DIR, STATIC_DIR
from app.core.pipeline import Pipeline

app = FastAPI(title="Faceless Tech Video Generator", version="1.0.0")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

# Mount static files (if any)
if os.path.exists(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """Serve the main web UI."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/health")
async def health():
    return {"status": "ok", "service": "faceless-tech-video-generator"}


@app.post("/api/generate")
async def generate_video(
    prompt: str = Form(...),
    product_images: list[UploadFile] = File(...),
    affiliate_link: str = Form(""),
    extra_context: str = Form(""),
    reference_video: UploadFile = File(None),
):
    """
    Run the full video generation pipeline.
    Drive and YouTube uploads are controlled by environment variables
    ENABLE_DRIVE_UPLOAD and ENABLE_YOUTUBE_UPLOAD.
    """
    # ─── Save uploaded files to temp ──────────────────────
    job_id = f"upload_{uuid.uuid4().hex[:8]}"
    upload_dir = os.path.join(TEMP_DIR, job_id)
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

    # ─── Run the pipeline ─────────────────────────────────
    pipeline = Pipeline()
    result = pipeline.run(
        prompt=prompt,
        product_images=image_paths,
        affiliate_link=affiliate_link or None,
        reference_video_path=ref_video_path,
        extra_context=extra_context or None,
        upload_to_drive=False,  # Controlled by env var inside pipeline
        upload_to_youtube=False, # Controlled by env var inside pipeline
    )

    # ─── Add download link to result ──────────────────────
    if result.get("video_path"):
        filename = os.path.basename(result["video_path"])
        result["download_url"] = f"/api/download/{filename}"

    # ─── Cleanup uploaded files ───────────────────────────
    shutil.rmtree(upload_dir, ignore_errors=True)

    return JSONResponse(content=result)


@app.get("/api/download/{filename}")
async def download_video(filename: str):
    """Download a generated video file."""
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
