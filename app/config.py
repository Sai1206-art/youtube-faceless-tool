"""
Configuration — all settings, API keys, and constants live here.
Load from environment variables / .env file.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ─── API Keys ──────────────────────────────────────────────
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
PEXELS_API_KEY = os.getenv("PEXELS_API_KEY", "")

# ─── Google Credentials ────────────────────────────────────
# Path to your service account JSON (for Drive + YouTube)
GOOGLE_CREDENTIALS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", "google-credentials.json")
YOUTUBE_CHANNEL_ID = os.getenv("YOUTUBE_CHANNEL_ID", "")

# ─── Paths ─────────────────────────────────────────────────
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
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
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "pNInz6obpgDQGcFmaJgB")  # "Adam" — professional male
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
DRIVE_FOLDER_ID = os.getenv("DRIVE_FOLDER_ID", "")  # Empty = upload to root

# ─── Stock Footage ─────────────────────────────────────────
PEXELS_PER_PAGE = 15
