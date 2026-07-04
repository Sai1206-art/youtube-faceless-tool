# Faceless Tech Video Generator

Automated pipeline that generates faceless YouTube tech product videos from your prompt + product photos.

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
