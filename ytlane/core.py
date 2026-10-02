"""
ytlane core — lane/action registries, the shared lane context and the runner.

Concepts (borrowed from fastlane):
  * action  — a single reusable step (generate a script, upload to YouTube, ...)
  * lane    — a named workflow in your Lanefile.py that chains actions
  * context — shared state ("lane_context") so actions can pick up the
              outputs of earlier actions without passing them by hand
  * hooks   — before_all / after_all / error, run around every lane
"""

import os
import sys
import time
import inspect
import importlib.util
from dataclasses import dataclass, field
from typing import Any, Callable, Optional


class LaneError(Exception):
    """Raised for user-facing errors (unknown lane, missing option, ...)."""


# ─── Registries ────────────────────────────────────────────

ACTIONS: dict[str, "ActionSpec"] = {}
LANES: dict[str, "LaneSpec"] = {}
HOOKS: dict[str, Optional[Callable]] = {"before_all": None, "after_all": None, "error": None}


@dataclass
class ActionSpec:
    name: str
    func: Callable
    description: str
    output: Optional[str] = None  # context key the return value is stored under


@dataclass
class LaneSpec:
    name: str
    func: Callable
    description: str


def action(name: Optional[str] = None, description: str = "", output: Optional[str] = None):
    """Register a function as an action. Signature: fn(ctx, **params)."""
    def decorator(func):
        action_name = name or func.__name__
        desc = description or (inspect.getdoc(func) or "").split("\n")[0]
        ACTIONS[action_name] = ActionSpec(action_name, func, desc, output)
        return func
    return decorator


def lane(func=None, *, name: Optional[str] = None, description: str = ""):
    """Register a function as a lane. Signature: fn(ctx, options)."""
    def decorator(f):
        lane_name = name or f.__name__
        desc = description or (inspect.getdoc(f) or "").split("\n")[0]
        LANES[lane_name] = LaneSpec(lane_name, f, desc)
        return f
    return decorator(func) if func else decorator


def before_all(func):
    """Hook: fn(ctx, lane_name) — runs before every lane."""
    HOOKS["before_all"] = func
    return func


def after_all(func):
    """Hook: fn(ctx, lane_name) — runs after every successful lane."""
    HOOKS["after_all"] = func
    return func


def error(func):
    """Hook: fn(ctx, lane_name, exception) — runs when a lane fails."""
    HOOKS["error"] = func
    return func


class Options(dict):
    """Lane options; a missing required key gives a friendly error."""

    def __missing__(self, key):
        raise LaneError(f"Missing option '{key}' — pass it as {key}:value")


# ─── Dry-run placeholder ───────────────────────────────────

class Placeholder:
    """Stand-in return value for actions skipped by --dry-run.

    Supports indexing/attribute access/iteration so lane code that pokes at
    results (script["title"], etc.) keeps working without real API calls.
    """

    def __init__(self, label: str):
        self._label = label

    def __getitem__(self, key):
        return Placeholder(f"{self._label}[{key!r}]")

    def __getattr__(self, key):
        if key.startswith("__"):
            raise AttributeError(key)
        return Placeholder(f"{self._label}.{key}")

    def get(self, key, default=None):
        return self[key]

    def __iter__(self):
        return iter(())

    def __len__(self):
        return 0

    def __bool__(self):
        return True

    def __repr__(self):
        return f"<dry-run {self._label}>"

    __str__ = __repr__


# ─── Context ───────────────────────────────────────────────

@dataclass
class StepRecord:
    action: str
    seconds: float
    status: str  # "ok" | "failed" | "skipped"


@dataclass
class Context:
    """Shared state for one ytlane run (fastlane's `lane_context`).

    Call actions as methods: ctx.generate_script(prompt="...").
    Read/write shared values with ctx["key"] / ctx.get("key").
    """

    dry_run: bool = False
    job_id: str = ""
    workdir: str = ""
    values: dict = field(default_factory=dict)
    steps: list = field(default_factory=list)
    lane_stack: list = field(default_factory=list)

    def __getitem__(self, key):
        return self.values[key]

    def __setitem__(self, key, value):
        self.values[key] = value

    def __contains__(self, key):
        return key in self.values

    def get(self, key, default=None):
        return self.values.get(key, default)

    def require(self, key: str, given: Any = None, hint: str = ""):
        """Return `given` if provided, else the context value, else fail clearly."""
        if given is not None:
            return given
        if key in self.values:
            return self.values[key]
        msg = f"Missing '{key}'"
        if hint:
            msg += f" — {hint}"
        raise LaneError(msg)

    def log(self, message: str):
        prefix = f"[{self.lane_stack[-1]}]" if self.lane_stack else "[ytlane]"
        print(f"{prefix} {message}", flush=True)

    def run_action(self, name: str, **params):
        spec = ACTIONS.get(name)
        if spec is None:
            raise LaneError(f"Unknown action '{name}'. Run `ytlane actions` to list them.")

        self.log(f"▶ {name}")
        start = time.time()
        if self.dry_run:
            result = Placeholder(name)
            self.steps.append(StepRecord(name, 0.0, "skipped"))
        else:
            try:
                result = spec.func(self, **params)
            except Exception:
                self.steps.append(StepRecord(name, time.time() - start, "failed"))
                raise
            self.steps.append(StepRecord(name, time.time() - start, "ok"))

        if spec.output:
            self.values[spec.output] = result
        return result

    def lane(self, name: str, **options):
        """Call another lane from inside a lane (hooks are not re-run)."""
        spec = LANES.get(name)
        if spec is None:
            raise LaneError(f"Unknown lane '{name}'.")
        self.lane_stack.append(name)
        try:
            return spec.func(self, Options(options))
        finally:
            self.lane_stack.pop()

    def __getattr__(self, name):
        # Only reached for attributes not defined on the dataclass.
        if name in ACTIONS:
            return lambda **params: self.run_action(name, **params)
        raise AttributeError(f"'{name}' is neither a context attribute nor a registered action")


# ─── Lanefile loading & running ────────────────────────────

def load_lanefile(path: str):
    if not os.path.exists(path):
        raise LaneError(f"No Lanefile found at '{path}'. Run `ytlane init` to create one.")
    # Make the project root importable so actions can `import app.core...`
    root = os.path.dirname(os.path.abspath(path))
    if root not in sys.path:
        sys.path.insert(0, root)
    spec = importlib.util.spec_from_file_location("ytlane_lanefile", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def print_summary(ctx: Context, lane_name: str, ok: bool, total: float):
    width = max([len(s.action) for s in ctx.steps] + [6])
    line = "+------+-" + "-" * width + "-+----------+---------+"
    print()
    print(line)
    print(f"| Step | {'Action'.ljust(width)} | Time (s) | Status  |")
    print(line)
    for i, s in enumerate(ctx.steps, 1):
        print(f"| {str(i).rjust(4)} | {s.action.ljust(width)} | {s.seconds:8.1f} | {s.status.ljust(7)} |")
    print(line)
    verdict = "finished successfully 🎉" if ok else "failed ❌"
    print(f"ytlane lane '{lane_name}' {verdict} ({total:.1f}s)")


def run_lane(name: str, options: dict, ctx: Context) -> Context:
    spec = LANES.get(name)
    if spec is None:
        available = ", ".join(sorted(LANES)) or "(none)"
        raise LaneError(f"Unknown lane '{name}'. Available lanes: {available}")

    start = time.time()
    ctx.lane_stack.append(name)
    try:
        if HOOKS["before_all"]:
            HOOKS["before_all"](ctx, name)
        ctx.values["lane_result"] = spec.func(ctx, Options(options))
        if HOOKS["after_all"]:
            HOOKS["after_all"](ctx, name)
    except Exception as exc:
        if HOOKS["error"]:
            try:
                HOOKS["error"](ctx, name, exc)
            except Exception as hook_exc:
                print(f"[ytlane] error hook itself failed: {hook_exc}")
        print_summary(ctx, name, ok=False, total=time.time() - start)
        raise
    finally:
        ctx.lane_stack.pop()
    print_summary(ctx, name, ok=True, total=time.time() - start)
    return ctx
