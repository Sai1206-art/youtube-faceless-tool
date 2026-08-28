"""
One-off editing run for the Riverside Ep.02 talking-head video.

Brief: full-frame B-roll cutaways on a 5-10s cadence (NOT continuous PiP),
original narration preserved, cover tablet-interaction moments with relevant
B-roll. Stages are checkpointed to JSON so we can inspect the plan before the
expensive render, and resume without re-paying for transcription/planning.

Run from repo root:  python3 scripts/run_edit.py <stage>
  stages: transcribe | plan | fetch | render | audio | all
"""
import os, sys, json
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
from app.core.broll_integrator import BrollIntegrator
from app.core.broll_composer import BrollComposer

BASE = "input/base.mp4"
WORK = "temp/edit02"
os.makedirs(WORK, exist_ok=True)
os.makedirs("output", exist_ok=True)

SEG_JSON   = f"{WORK}/segments.json"
PLAN_JSON  = f"{WORK}/plan.json"
FETCH_JSON = f"{WORK}/inserts.json"
BROLL_OUT  = "output/riverside_ep02_broll.mp4"
FINAL_OUT  = "output/riverside_ep02_final.mp4"

client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
bi = BrollIntegrator()


def tc(s): return f"{int(s)//60}:{int(s)%60:02d}"


def stage_transcribe():
    info = bi.probe_video(BASE)
    json.dump(info, open(f"{WORK}/info.json", "w"))
    audio = bi._extract_audio(BASE, WORK, "edit02")
    print("extracted audio:", audio, os.path.getsize(audio)//1024, "KB")
    segs = bi.transcribe(audio)
    json.dump(segs, open(SEG_JSON, "w"), indent=1)
    print(f"transcribed {len(segs)} segments, {info['duration']:.1f}s")
    return segs


def stage_plan():
    info = json.load(open(f"{WORK}/info.json"))
    segs = json.load(open(SEG_JSON))
    dur = info["duration"]
    lines = [f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}" for s in segs if s.get("text")]
    transcript = "\n".join(lines)[:14000]

    instruction = f"""You are a senior YouTube editor cutting B-roll for a {dur:.0f}-second
talking-head episode ("Riverside Magic Ep.02"). Here is the time-aligned transcript.

Produce a B-roll plan that keeps engagement HIGH with FULL-FRAME cutaways — the
B-roll fully covers the frame for its window while the speaker keeps talking
underneath (audio continues). Do NOT keep speaker and B-roll side-by-side.

Rules:
- Place a cutaway roughly every 5-10 seconds where it ADDS VALUE (illustrates a
  noun/place/action/tool the speaker mentions). Leave the speaker on camera in
  between so it breathes — aim for 45-60% total coverage, never wall-to-wall.
- Whenever the speaker is looking at / reading / scrolling / reacting to content
  on a tablet or screen, ALWAYS cover it with a matching cutaway (query like
  "tablet scrolling closeup", "person using tablet", "app interface screen"),
  and mark "tablet": true on that insert.
- Each cutaway 3-6 seconds. Inserts must NOT overlap and stay within 0..{dur:.1f}.
- "query": 2-4 words a stock site (Pexels) actually has — concrete, filmable
  visuals, never abstract ideas or the literal words.

Return ONLY valid JSON:
{{"inserts":[{{"start":0.0,"end":4.0,"query":"...","tablet":false}}, ...]}}

Transcript:
{transcript}
"""
    resp = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": instruction}],
        temperature=0.6,
        response_format={"type": "json_object"},
    )
    raw = json.loads(resp.choices[0].message.content).get("inserts", [])
    # Normalize with the integrator (clamp, de-overlap, split long, cap), then
    # force full-frame layout and carry the tablet flag.
    norm = bi._normalize_plan(
        [{"start": r.get("start"), "end": r.get("end"),
          "query": r.get("query", ""), "layout": "fullscreen"} for r in raw],
        dur,
    )
    # Re-attach tablet flags by nearest original insert.
    def is_tablet(t):
        for r in raw:
            try:
                if float(r.get("start", -9)) - 1 <= t <= float(r.get("end", -9)) + 1:
                    return bool(r.get("tablet"))
            except (TypeError, ValueError):
                pass
        return False
    for n in norm:
        n["layout"] = "fullscreen"
        n["tablet"] = is_tablet(n["start"])
    json.dump(norm, open(PLAN_JSON, "w"), indent=1)
    covered = sum(n["end"] - n["start"] for n in norm)
    print(f"planned {len(norm)} cutaways, {covered:.0f}s = {covered/dur*100:.0f}% coverage, "
          f"{sum(1 for n in norm if n['tablet'])} tablet-covers")
    for n in norm:
        print(f"  {tc(n['start'])}-{tc(n['end'])}  {'[TABLET] ' if n['tablet'] else ''}{n['query']}")
    return norm


def stage_fetch():
    info = json.load(open(f"{WORK}/info.json"))
    plan = json.load(open(PLAN_JSON))
    orientation = "portrait" if info["height"] > info["width"] else "landscape"
    used = set()
    inserts = []
    for i, p in enumerate(plan):
        clip = bi.stock.fetch_broll(p["query"], i, output_dir=WORK, job_id="edit02",
                                    orientation=orientation, used_video_ids=used)
        if clip:
            inserts.append({"start": p["start"], "end": p["end"], "clip_path": clip["path"],
                            "clip_duration": clip["duration"], "layout": "fullscreen",
                            "query": p["query"], "tablet": p["tablet"]})
            print(f"  ✓ {tc(p['start'])} '{p['query']}' -> {os.path.basename(clip['path'])}")
        else:
            print(f"  ✗ no clip for '{p['query']}' @ {tc(p['start'])}")
    json.dump(inserts, open(FETCH_JSON, "w"), indent=1)
    print(f"fetched {len(inserts)}/{len(plan)} clips")
    return inserts


def stage_render():
    info = json.load(open(f"{WORK}/info.json"))
    inserts = json.load(open(FETCH_JSON))
    comp = BrollComposer()
    out = comp.compose(BASE, inserts, base_w=info["width"], base_h=info["height"],
                       job_id="edit02", output_path=BROLL_OUT)
    print("rendered:", out)


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    if stage in ("transcribe", "all"): stage_transcribe()
    if stage in ("plan", "all"): stage_plan()
    if stage in ("fetch", "all"): stage_fetch()
    if stage in ("render", "all"): stage_render()
