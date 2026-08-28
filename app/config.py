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
RESOLUTION = (640, 480)  # SD (optimized for Render Free Tier 512MB RAM)

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

# ─── B-roll Integration (overlay B-roll onto an existing base video) ──
# Transcription model used to time-align the speaker's words so B-roll
# can be placed at the right moments.
WHISPER_MODEL = "whisper-1"
# The planning LLM decides which words/phrases deserve B-roll and how to
# lay it out over the speaker.
BROLL_PLANNER_MODEL = "gpt-4o"
# Minimum length (seconds) of a single B-roll insert. Shorter beats feel
# glitchy; the planner merges anything shorter than this.
BROLL_MIN_CLIP = 1.8
# Maximum length (seconds) of a single B-roll insert before we force a cut
# to a new clip — keeps long stretches visually fresh.
BROLL_MAX_CLIP = 6.0
# Target share of the talking track that should be covered by B-roll.
# 0.85 = "at maximum places" as requested — nearly wall-to-wall B-roll.
BROLL_COVERAGE_TARGET = 0.85
# Default layout when the planner does not specify one. "pip_topright"
# keeps the speaker on screen with B-roll rolling in a large inset.
BROLL_DEFAULT_LAYOUT = "pip_topright"
# Fraction of frame width the picture-in-picture inset occupies.
BROLL_PIP_SCALE = 0.46
# Margin (px) around the PiP inset.
BROLL_PIP_MARGIN = 24
# Hard cap on number of B-roll inserts in one video (bounds ffmpeg command
# size and render time). Set generously so "max places" still applies.
BROLL_MAX_INSERTS = 60

# ─── Feature Flags ─────────────────────────────────────────
ENABLE_DRIVE_UPLOAD = os.getenv("ENABLE_DRIVE_UPLOAD", "false").lower() == "true"
ENABLE_YOUTUBE_UPLOAD = os.getenv("ENABLE_YOUTUBE_UPLOAD", "false").lower() == "true"
