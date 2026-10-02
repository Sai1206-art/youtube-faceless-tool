import os
import textwrap

import pytest

from ytlane import core
from ytlane.cli import main, parse_options
from ytlane.actions import as_list, load_metadata


@pytest.fixture(autouse=True)
def clean_registries():
    saved = (dict(core.ACTIONS), dict(core.LANES), dict(core.HOOKS))
    core.LANES.clear()
    core.HOOKS.update(before_all=None, after_all=None, error=None)
    yield
    core.ACTIONS.clear(); core.ACTIONS.update(saved[0])
    core.LANES.clear(); core.LANES.update(saved[1])
    core.HOOKS.clear(); core.HOOKS.update(saved[2])


def write_lanefile(tmp_path, body):
    path = tmp_path / "Lanefile.py"
    path.write_text(textwrap.dedent(body))
    return str(path)


def test_parse_options():
    assert parse_options(["prompt:Best earbuds", "drive:true", "url:https://a.b/c"]) == {
        "prompt": "Best earbuds", "drive": True, "url": "https://a.b/c",
    }


def test_as_list_handles_dirs_and_csv(tmp_path):
    (tmp_path / "b.png").write_bytes(b"")
    (tmp_path / "a.jpg").write_bytes(b"")
    (tmp_path / "notes.txt").write_text("x")
    assert as_list(str(tmp_path)) == [str(tmp_path / "a.jpg"), str(tmp_path / "b.png")]
    assert as_list("x.jpg, y.jpg") == ["x.jpg", "y.jpg"]


def test_lane_chains_actions_through_context(tmp_path, capsys):
    lanefile = write_lanefile(tmp_path, """
        from ytlane import lane, action, before_all, after_all

        calls = []

        @action(output="script")
        def fake_script(ctx, prompt):
            return {"title": prompt.upper()}

        @action(output="video_path")
        def fake_render(ctx):
            return ctx["script"]["title"] + ".mp4"

        @before_all
        def setup(ctx, name):
            ctx["hooks"] = ["before:" + name]

        @after_all
        def done(ctx, name):
            ctx["hooks"].append("after:" + name)

        @lane
        def draft(ctx, options):
            ctx.fake_script(prompt=options["prompt"])
            ctx.fake_render()
    """)
    assert main(["draft", "prompt:hello", "--lanefile", lanefile]) == 0
    out = capsys.readouterr().out
    assert "fake_script" in out and "finished successfully" in out


def test_missing_option_and_error_hook(tmp_path, capsys):
    lanefile = write_lanefile(tmp_path, """
        from ytlane import lane, error

        @lane
        def draft(ctx, options):
            options["prompt"]

        @error
        def on_error(ctx, name, exc):
            print("HOOK:", exc)
    """)
    assert main(["draft", "--lanefile", lanefile]) == 1
    captured = capsys.readouterr()
    assert "HOOK: Missing option 'prompt'" in captured.out
    assert "failed" in captured.out


def test_dry_run_skips_real_actions(tmp_path, capsys):
    # Uses the real Lanefile: no API keys or heavy deps are touched.
    lanefile = os.path.join(os.path.dirname(__file__), "..", "Lanefile.py")
    assert main(["draft", "prompt:x", "images:a.jpg", "--dry-run", "--lanefile", lanefile]) == 0
    out = capsys.readouterr().out
    for step in ("generate_script", "voiceover", "fetch_stock", "compose_video", "upload_youtube"):
        assert step in out
    assert "skipped" in out


def test_unknown_lane(tmp_path, capsys):
    lanefile = write_lanefile(tmp_path, "from ytlane import lane\n")
    assert main(["nope", "--lanefile", lanefile]) == 1
    assert "Unknown lane 'nope'" in capsys.readouterr().err


def test_load_metadata_overrides_script(tmp_path):
    (tmp_path / "title.txt").write_text("My Title\n")
    (tmp_path / "tags.txt").write_text("tech\nearbuds, review")
    ctx = core.Context(job_id="t")
    ctx["script"] = {"title": "old", "description": "keep"}
    meta = load_metadata(ctx, path=str(tmp_path))
    assert meta == {"title": "My Title", "tags": ["tech", "earbuds", "review"]}
    assert ctx["script"] == {"title": "My Title", "description": "keep",
                             "tags": ["tech", "earbuds", "review"]}


def test_init_creates_lanefile(tmp_path):
    path = str(tmp_path / "Lanefile.py")
    assert main(["init", "--lanefile", path]) == 0
    assert "@lane" in open(path).read()
    assert main(["init", "--lanefile", path]) == 1  # refuses to overwrite
