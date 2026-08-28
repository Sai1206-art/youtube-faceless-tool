# Faceless Tech Video Generator

Automated pipeline that generates faceless YouTube tech product videos from your prompt + product photos.

## Two modes

1. **Generate from scratch** — prompt + product photos → full faceless video (script → voiceover → stock footage → composed video).
2. **Add B-roll to an existing video** — upload a talking-head / base video and the tool overlays relevant Pexels B-roll at maximum relevant spots, keeping the speaker on screen while B-roll rolls in a picture-in-picture inset (with occasional full-frame cutaways).

## B-roll Integration

Upload a base video on the web UI (top card, "Add B-roll to an existing video") or `POST /api/broll` with a `base_video` file.

How it works:

```
Base video
  → probe (dimensions / duration / audio)
  → Whisper transcribes the speech with timestamps
  → GPT-4o plans B-roll: which moments, what to search, how to lay it out
  → Pexels clips fetched for each window (distinct clip per insert)
  → FFmpeg bakes every clip onto the base video in one pass
```

- **Coverage:** aims to cover ~85% of the talking track so the video stays engaging "at max places". Tune with `BROLL_COVERAGE_TARGET`.
- **Layout:** default is a large picture-in-picture inset in a rotating corner (`BROLL_PIP_SCALE`, `BROLL_PIP_MARGIN`), so the person stays visible with B-roll rolling. The planner uses full-frame cutaways when the speaker names a concrete object/place.
- **Audio:** the original speaker audio is always preserved; B-roll audio is dropped.
- **Graceful fallback:** if transcription or GPT-4o is unavailable, a heuristic planner still spreads B-roll across the timeline. If a clip can't be found or the render fails, you still get a valid video back.

Only `OPENAI_API_KEY` (Whisper + GPT-4o planning) and `PEXELS_API_KEY` are needed for this mode — no ElevenLabs or Google credentials required.

## Workflow

```
User Input (prompt + photos + affiliate link)
  → GPT-4o generates structured video script
  → ElevenLabs generates voiceover audio
  → Pexels stock footage fetched for B-roll
  → MoviePy composes final video (images + stock + TTS + text + music)
  → Google Drive upload
  → YouTube upload (private/draft for review)
```

## Setup

### 1. Install dependencies

```bash
cd youtube-faceless-tool
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Get API Keys

| Service | What it does | Where to get |
|---------|-------------|--------------|
| **OpenAI** | Script generation (GPT-4o) | https://platform.openai.com/api-keys |
| **ElevenLabs** | Voiceover TTS | https://elevenlabs.io/app/settings/api-keys |
| **Pexels** | Stock footage (free) | https://www.pexels.com/api/ |
| **Google Cloud** | Drive + YouTube upload | https://console.cloud.google.com/ |

### 3. Google Credentials Setup

You need TWO types of Google credentials:

#### A. Service Account (for Google Drive)
1. Go to Google Cloud Console → APIs & Services → Credentials
2. Create Service Account → download JSON key
3. Save as `google-credentials.json` in project root
4. Enable **Google Drive API**

#### B. OAuth Client ID (for YouTube)
1. Google Cloud Console → Credentials → Create Credentials → OAuth client ID
2. Choose "Desktop app"
3. Download JSON → save as `youtube-oauth-client.json`
4. Enable **YouTube Data API v3**
5. First run will open a browser for one-time consent — token is cached after that

### 4. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 5. (Optional) Background music

Place royalty-free music files in a `music/` directory at the project root:

```bash
mkdir music
# Add your .mp3 files here
```

### 6. Run

```bash
python -m uvicorn app.main:app --reload --port 8000
```

Open http://localhost:8000

## Usage

1. Enter your prompt (what kind of video you want)
2. Upload product photos (at least 1)
3. Optionally add:
   - Reference video
   - **Affiliate link** → goes into YouTube description top lines
   - Extra context (tone, audience, etc.)
4. Click Generate
5. Video is uploaded to Drive + YouTube (private)
6. Review on YouTube Studio, then publish when ready

## Tech Stack

- **Backend:** Python, FastAPI
- **LLM:** OpenAI GPT-4o (multimodal — reads product images + video frames)
- **TTS:** ElevenLabs
- **Stock Footage:** Pexels API (free)
- **Video Composition:** MoviePy + FFmpeg + Pillow
- **Cloud Uploads:** Google Drive API + YouTube Data API v3

## Cost Estimate Per Video

| Component | Cost |
|-----------|------|
| GPT-4o (script + image analysis) | ~$0.03 |
| ElevenLabs TTS (~90s audio) | ~$0.10 |
| Pexels stock footage | Free |
| MoviePy processing | Free (compute) |
| **Total per video** | **~$0.13** |

## Project Structure

```
youtube-faceless-tool/
├── app/
│   ├── __init__.py
│   ├── main.py              ← FastAPI server
│   ├── config.py            ← All settings & API keys
│   ├── templates/
│   │   └── index.html       ← Web UI
│   ├── static/
│   └── core/
│       ├── __init__.py
│       ├── script_generator.py  ← GPT-4o script generation
│       ├── tts_engine.py        ← ElevenLabs voiceover
│       ├── stock_footage.py     ← Pexels stock footage fetcher
│       ├── video_composer.py    ← MoviePy video composition
│       ├── drive_uploader.py    ← Google Drive upload
│       ├── youtube_uploader.py  ← YouTube upload (private)
│       └── pipeline.py          ← Orchestrates everything
├── output/                  ← Final videos land here
├── temp/                    ← Temporary processing files
├── music/                   ← (Optional) royalty-free background music
├── requirements.txt
├── .env.example
└── README.md
```

## Notes

- Videos are uploaded to YouTube as **private** (equivalent to draft). YouTube API has no "draft" status — private is the closest.
- YouTube API marks uploaded videos with `containsSyntheticMedia: true` (AI-generated content disclosure).
- The first time you run with YouTube upload enabled, a browser window opens for OAuth consent. After that, the token is cached.
- Background music is optional — if no music file is found in `music/`, the video will have voiceover only.
- Estimated processing time per video: 5-10 minutes depending on stock footage downloads and video rendering speed.
