"""
Lanefile — ytlane workflows for this channel (think fastlane's Fastfile).

    python -m ytlane                                   # list lanes
    python -m ytlane draft prompt:"Top 3 budget earbuds" images:photos/ affiliate:https://amzn.to/x
    python -m ytlane script prompt:"..." images:photos/    # LLM only → script.json to review
    python -m ytlane render script:temp/job_x/script.json  # render an edited script, no upload
    python -m ytlane release script:script.json privacy:unlisted
    python -m ytlane draft ... --dry-run                   # see the steps, call no APIs
"""

from ytlane import lane, before_all, after_all, error


@before_all
def setup(ctx, lane_name):
    ctx.ensure_env(keys="OPENAI_API_KEY,ELEVENLABS_API_KEY,PEXELS_API_KEY")


@lane
def draft(ctx, options):
    """Full pipeline: script → voiceover → B-roll → video → YouTube (private)."""
    ctx.generate_script(
        prompt=options["prompt"],
        images=options["images"],
        affiliate_link=options.get("affiliate"),
        extra_context=options.get("context"),
    )
    ctx.save_script()
    ctx.lane("render")
    if options.get("drive"):
        ctx.upload_drive()
    ctx.upload_youtube(privacy=options.get("privacy", "private"))


@lane
def script(ctx, options):
    """Only generate the script and save it as JSON for review/editing."""
    ctx.generate_script(
        prompt=options["prompt"],
        images=options["images"],
        affiliate_link=options.get("affiliate"),
        extra_context=options.get("context"),
    )
    ctx.save_script(path=options.get("out"))


@lane
def render(ctx, options):
    """Render a video from the current (or a saved) script — no uploads."""
    if options.get("script"):
        ctx.load_script(path=options["script"])
    ctx.load_metadata(path=options.get("metadata", "metadata"))
    ctx.voiceover()
    ctx.fetch_stock()
    ctx.compose_video()


@lane
def release(ctx, options):
    """Render a reviewed script and upload it to YouTube."""
    ctx.lane("render", **options)
    ctx.upload_youtube(privacy=options.get("privacy", "private"))


@after_all
def done(ctx, lane_name):
    if "youtube" in ctx:
        ctx.notify(message=f"✅ {lane_name}: {ctx['youtube'].get('video_url')}")


@error
def on_error(ctx, lane_name, exc):
    ctx.notify(message=f"❌ Lane '{lane_name}' failed: {exc}")
