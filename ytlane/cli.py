"""
ytlane CLI.

    python -m ytlane                      # list lanes
    python -m ytlane <lane> key:value ... # run a lane
    python -m ytlane run <action> key:value ...
    python -m ytlane actions              # list built-in + custom actions
    python -m ytlane init                 # create a starter Lanefile.py

Flags: --lanefile PATH  --env NAME (loads .env.NAME)  --dry-run  --job-id ID
"""

import os
import sys
import uuid

from ytlane.core import ACTIONS, LANES, Context, LaneError, load_lanefile, run_lane, print_summary

STARTER_LANEFILE = '''"""Lanefile — your ytlane workflows. Run `python -m ytlane` to list lanes."""

from ytlane import lane, before_all, error


@before_all
def setup(ctx, lane_name):
    ctx.ensure_env(keys="OPENAI_API_KEY,ELEVENLABS_API_KEY,PEXELS_API_KEY")


@lane
def draft(ctx, options):
    """Generate a video and upload it to YouTube as private."""
    ctx.generate_script(prompt=options["prompt"], images=options["images"])
    ctx.voiceover()
    ctx.fetch_stock()
    ctx.compose_video()
    ctx.upload_youtube(privacy="private")


@error
def on_error(ctx, lane_name, exc):
    ctx.notify(message=f"Lane {lane_name} failed: {exc}")
'''

USAGE = __doc__


def parse_value(raw: str):
    lowered = raw.lower()
    if lowered in ("true", "yes"):
        return True
    if lowered in ("false", "no"):
        return False
    return raw


def parse_options(pairs: list[str]) -> dict:
    """fastlane-style `key:value` arguments → dict."""
    options = {}
    for pair in pairs:
        if ":" not in pair:
            raise LaneError(f"Invalid option '{pair}' — use key:value")
        key, value = pair.split(":", 1)
        options[key.strip()] = parse_value(value.strip())
    return options


def split_flags(argv: list[str]):
    flags = {"lanefile": "Lanefile.py", "env": None, "dry_run": False, "job_id": None}
    positionals = []
    it = iter(argv)
    for arg in it:
        if arg in ("-h", "--help"):
            flags["help"] = True
        elif arg == "--dry-run":
            flags["dry_run"] = True
        elif arg in ("--lanefile", "--env", "--job-id"):
            try:
                flags[arg[2:].replace("-", "_")] = next(it)
            except StopIteration:
                raise LaneError(f"{arg} needs a value")
        else:
            positionals.append(arg)
    return flags, positionals


def load_env(name):
    try:
        from dotenv import load_dotenv
    except ImportError:
        load_dotenv = None
    if name:
        path = f".env.{name}"
        if not os.path.exists(path):
            raise LaneError(f"--env {name}: {path} not found")
        if load_dotenv:
            # Loaded first so it wins over the plain .env loaded by app.config.
            load_dotenv(path, override=True)
    if load_dotenv:
        load_dotenv()


def list_lanes():
    if not LANES:
        print("No lanes defined in your Lanefile.")
        return
    print("Available lanes:\n")
    width = max(len(n) for n in LANES)
    for name, spec in LANES.items():
        print(f"  {name.ljust(width)}  {spec.description}")
    print("\nRun one with: python -m ytlane <lane> key:value ...")


def list_actions():
    print("Available actions:\n")
    width = max(len(n) for n in ACTIONS)
    for name, spec in sorted(ACTIONS.items()):
        out = f"  → ctx['{spec.output}']" if spec.output else ""
        print(f"  {name.ljust(width)}  {spec.description}{out}")


def init(path):
    if os.path.exists(path):
        raise LaneError(f"{path} already exists")
    with open(path, "w", encoding="utf-8") as f:
        f.write(STARTER_LANEFILE)
    print(f"✓ Created {path}. Try: python -m ytlane draft prompt:'...' images:photos/")


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    try:
        flags, args = split_flags(argv)
        if flags.get("help"):
            print(USAGE)
            return 0

        command = args[0] if args else "lanes"
        if command == "init":
            init(flags["lanefile"])
            return 0

        load_env(flags["env"])
        import ytlane.actions  # noqa: F401  register built-ins

        if command == "actions":
            if os.path.exists(flags["lanefile"]):
                load_lanefile(flags["lanefile"])  # include custom actions
            list_actions()
            return 0

        ctx = Context(
            dry_run=flags["dry_run"],
            job_id=flags["job_id"] or f"job_{uuid.uuid4().hex[:8]}",
        )

        if command == "run":
            if len(args) < 2:
                raise LaneError("Usage: python -m ytlane run <action> key:value ...")
            if os.path.exists(flags["lanefile"]):
                load_lanefile(flags["lanefile"])
            result = ctx.run_action(args[1], **parse_options(args[2:]))
            print_summary(ctx, f"run {args[1]}", ok=True, total=sum(s.seconds for s in ctx.steps))
            if result is not None:
                print(result)
            return 0

        load_lanefile(flags["lanefile"])
        if command == "lanes":
            list_lanes()
            return 0

        print(f"🚀 ytlane: lane '{command}' (job {ctx.job_id}{', dry run' if ctx.dry_run else ''})")
        run_lane(command, parse_options(args[1:]), ctx)
        return 0

    except LaneError as e:
        print(f"[!] {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"[!] {type(e).__name__}: {e}", file=sys.stderr)
        return 1
