"""
Configuration — all settings, API keys, and constants live here.
Load from environment variables / .env file.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── FFmpeg binary path (set lazily) ───────────────────────
# imageio-ffmpeg bundles its own ffmpeg binary. We set the path
# lazily to avoid downloading during startup.
FFMPEG_BINARY = ""
def _setup_ffmpeg():
    global FFMPEG_BINARY
    try:
        import imageio_ffmpeg
        FFMPEG_BINARY = imageio_ffmpeg.get_ffmpeg_exe()
        os.environ["FFMPEG_BINARY"] = FFMPEG_BINARY
        os.environ["IMAGEIO_FFMPEG_EXE"] = FFMPEG_BINARY
    except Exception as e:
        print(f"⚠️ Could not setup ffmpeg: {e}")

# ─── API Keys ──────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

# ─── Google Credentials ────────────────────────────────────
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "google-credentials.json")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "")

# ─── Paths ─────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# On Render/Docker, use /app/temp and /app/output
if os.path.exists("/app/temp"):
    TEMP_DIR = "/app/temp"
    OUTPUT_DIR = "/app/output"
else:
    TEMP_DIR = os.path.join(BASE_DIR, "temp")
    OUTPUT_DIR = os.path.join(os.path.dirname(BASE_DIR), "output")

TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
STATIC_DIR = os.path.join(BASE_DIR, "static")

# Ensure dirs exist
os.makedirs(TEMP_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# ─── Video Settings ────────────────────────────────────────
MAX_VIDEO_DURATION = 120  # 2 minutes in seconds
TARGET_DURATION = 90      # aim for 90s, max 120s
FPS = 30
RESOLUTION = (1920, 1080)  # Full HD

# ─── TTS Settings ──────────────────────────────────────────
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")  # "Adam"
TTS_MODEL = "eleven_turbo_v2"
TTS_VOICE_SETTINGS = {
    "stability": 0.5,
    "similarity_boost": 0.75,
    "style": 0.35,
    "use_speaker_boost": True,
}

# ─── LLM Settings ──────────────────────────────────────────
LLM_MODEL = "gpt-4o"
LLM_MAX_TOKENS = 4096
LLM_TEMPERATURE = 0.7

# ─── Drive Settings ────────────────────────────────────────
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "")

# ─── Stock Footage ─────────────────────────────────────────
PEXELS_PER_PAGE = 15

# ─── Feature Flags ─────────────────────────────────────────
ENABLE_DRIVE_UPLOAD = os.getenv("ENABLE_DRIVE_UPLOAD", "false").lower() == "true"
ENABLE_YOUTUBE_UPLOAD = os.getenv("ENABLE_YOUTUBE_UPLOAD", "false").lower() == "true"
