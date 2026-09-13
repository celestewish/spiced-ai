# Unity Alpha Readiness Spec

Scope: the three priorities set for pre-alpha, in order of positioning
weight — Spiced is being sold specifically as **Unity debugging software**
for this release, not the three-engine story from the prior spec. Godot/
Unreal support keeps shipping underneath, but nothing in this document
should be read as walking that back; it is scoping *this alpha's marketing
and polish focus*, not the roadmap. Worth saying out loud since it's a
real narrowing from "automated testing, debugging, and feedback across
three engines" (the framing two specs ago) to "Unity debugging software"
(this message) — a deliberate call, not a silent one.

Verified against the repo as of commit `9f38899066049396186bbe1d417451f65ab7a1fd`
on branch `connect-project-setup-simplification` (not yet merged to `main`).
`SETUP_SIMPLIFICATION_SPEC.md`'s three findings are confirmed shipped:
auto-detect-engine-from-folder, Godot/Unreal executable discovery, the
in-app API key field, and the `packaging/` installer scaffold (PyInstaller
spec + Inno Setup script + vendored-ffmpeg support) all exist and match
that spec. Two things from `packaging/README.md` are flagged there as open
by whoever built it, not by this scan, and are worth carrying into alpha
planning regardless of the three priorities below:

- **Unresolved `Qt6Core.dll` crash on a from-scratch PyInstaller build**
  (PySide6 6.11.1 / PyInstaller 6.22.2 / Python 3.14) — the frozen exe
  faults on launch even with `--smoke-test`, while the unfrozen app runs
  fine. Nobody has root-caused this yet. If the alpha installer is meant
  to ship from this `packaging/` setup, this needs to be resolved (or the
  toolchain pinned to an older PySide6/Python combo that doesn't hit it)
  *before* an alpha build goes out the door — an installer that crashes
  Spiced on first launch is worse than no installer.
- **Code signing is an open, unmade decision** (`packaging/README.md`'s
  own words) — an unsigned `.exe` trips Windows SmartScreen, which reads
  as "this is a virus" to the non-technical indie devs the installer
  exists for. Roughly $100-400/yr. Not urgent for priority 1 below, but
  it's the kind of thing that's cheap to decide now and expensive to
  discover from support messages after alpha users start installing.

---

## Priority 1 — Framerate: 15fps → 60fps

### Root cause, confirmed

`BUGFIX_SPEC`'s Root Causes A and B are fixed and stay fixed — verified by
reading the current source, not just trusting the doc:

- `ui/effects/background_scene.py`: `OceanBackgroundWidget` ticks at
  `_TICK_INTERVAL_MS = 33` (~30fps, intentionally halved for a decorative
  background), caches its sky/sun/island backdrop as a `QPixmap` keyed on
  `(width, height, px, py, dpr)`, and caches per-layer wave `QPainterPath`s
  instead of rebuilding them every frame.
- `ui/widgets/pill_button.py`: `PillButton.paintEvent` builds a cache key
  from every paint-relevant input (size, dpr, radius, state, text, icon,
  font, palette, theme, fill bucket) and reuses the cached pixmap when
  nothing in that key changed.

Root Cause C — flagged in the original bugfix pass as "the most
speculative... worth verifying with cProfile before assuming it's a live
contributor" — was **never fixed or verified**, and is now the leading
suspect for the remaining 15fps→60fps gap:

```python
# main_window.py, lines 46-50
# Card/ReadinessCard frames are dashboard.py's -- rebuilt fresh on every
# refresh(), so they get their own shadow applied at construction time (see
# dashboard.py's _card()) rather than here, where a one-time findChildren
# pass would only ever catch the very first set built.
_SHADOWED_FRAME_NAMES = {"Panel", "Sidebar", "ContextPanel", "TopBar"}

# main_window.py, lines 243-255
def _apply_glass_elevation(self) -> None:
    """Real drop-shadow elevation on the glass panels/cards -- Qt QSS has
    no ``box-shadow`` (see ui.theme's module docstring), so this is done
    in code instead, in one central place rather than touching every one
    of the 14 screen files that build a #Card."""
    for frame in self.findChildren(QFrame):
        if frame.objectName() not in _SHADOWED_FRAME_NAMES:
            continue
        shadow = QGraphicsDropShadowEffect(frame)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(20, 10, 40, 90))
        frame.setGraphicsEffect(shadow)
```

and, from `_build_workspace` (line ~490):

```python
def _build_workspace(self) -> QFrame:
    panel = QFrame()
    panel.setObjectName("Panel")          # <- one of the four shadowed names
    outer = QVBoxLayout(panel)
    outer.setContentsMargins(6, 6, 6, 6)

    self._stack = FadeStackedWidget(services=self._services)
    ...
    self._stack.addWidget(self._dashboard_screen)
    self._stack.addWidget(self._projects_screen)
    self._stack.addWidget(self._debugging_screen)
    self._stack.addWidget(self._testing_screen)
    self._stack.addWidget(self._feedback_screen)
    self._stack.addWidget(self._marketing_screen)
    self._stack.addWidget(self._business_screen)
    self._stack.addWidget(self._art_screen)
    self._stack.addWidget(self._audio_screen)
    self._stack.addWidget(self._animation_screen)
    self._stack.addWidget(self._shaders_vfx_screen)
    self._stack.addWidget(self._team_screen)
    self._stack.addWidget(self._roadmap_screen)
    self._stack.addWidget(self._settings_screen)
    ...
    outer.addWidget(self._stack)
    return panel
```

`Panel` is not a static decorative frame like `Sidebar` or `TopBar` — it's
the direct parent of `self._stack`, the `FadeStackedWidget` holding all 14
screens, including the Debugging Buddy screen that streams AI response
text token-by-token and runs a `water_fill` loading animation on its
Analyze button. `QGraphicsDropShadowEffect` works by intercepting paint on
its owning widget and rasterizing that widget's *entire subtree* to an
offscreen buffer, blurring it, then compositing — on every single repaint
of anything inside it. That means every character of streamed AI text,
every tick of the water-fill button, and every frame of a screen-to-screen
crossfade currently pays for a full-subtree offscreen rasterize + blur of
whichever screen is active, on top of whatever that screen's own paint
work costs. `Sidebar`/`ContextPanel`/`TopBar` don't have this problem
because nothing inside them repaints at animation frequency.

This was never profiled — `tools/profile_effects.py` benchmarks
`OceanBackgroundWidget`, `PillButton`, `FadeStackedWidget`, and
`WaterSplashOverlay` in isolation, but nothing in it constructs a `Panel`
with the drop-shadow effect applied, so the existing benchmark suite would
not have caught this even if someone had looked.

### Fix

**Step 1 — drop `Panel` from the shadowed set.** It's the one entry in
`_SHADOWED_FRAME_NAMES` sitting in the live animation path; `Sidebar`,
`ContextPanel`, and `TopBar` are cheap to keep exactly as they are.

```python
# main_window.py, line 50
_SHADOWED_FRAME_NAMES = {"Sidebar", "ContextPanel", "TopBar"}
```

This alone should recover most of the gap. It does remove Panel's drop
shadow visually, so:

**Step 2 (visual parity, optional but recommended)** — replace the real
`QGraphicsDropShadowEffect` on `Panel` with a static, pre-rendered shadow
drawn once rather than recomputed every repaint. The cheapest version:
render a small shadow-gradient `QPixmap` once (same blur radius/offset/
color as today: `blurRadius=24, offset=(0, 6), color=(20, 10, 40, 90)`)
and paint it as a border/backdrop behind `panel` in `_build_workspace`,
or apply it via a stylesheet `border-image`/background trick instead of a
live graphics effect. This keeps the glass-panel look without putting a
live offscreen-composite in the hot path. Worth doing, but Step 1 is the
one that actually fixes the framerate — treat Step 2 as a follow-up polish
pass, not a blocker.

**Step 3 — verify with a number, not a guess.** Extend
`tools/profile_effects.py` with a benchmark that actually exercises this
path, since nothing currently does:

```python
# New in tools/profile_effects.py

def _bench_shadowed_panel(shadowed: bool) -> list[float]:
    parent = QWidget()
    parent.resize(1280, 800)
    panel = QFrame()
    panel.setObjectName("Panel")
    layout = QVBoxLayout(panel)
    stack = FadeStackedWidget(parent, services=_FakeServices())
    pages = [QWidget() for _ in range(14)]  # matches main_window's 14 screens
    for page in pages:
        page.setObjectName("page")
        stack.addWidget(page)
    layout.addWidget(stack)
    parent_layout = QVBoxLayout(parent)
    parent_layout.addWidget(panel)
    if shadowed:
        shadow = QGraphicsDropShadowEffect(panel)
        shadow.setBlurRadius(24)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(20, 10, 40, 90))
        panel.setGraphicsEffect(shadow)
    parent.show()
    target = QPixmap(1280, 800)

    for _ in range(5):
        panel.render(target)

    times: list[float] = []
    for _ in range(_OCEAN_ITERATIONS):
        start = time.perf_counter()
        panel.render(target)
        times.append((time.perf_counter() - start) * 1000.0)

    parent.deleteLater()
    _app.processEvents()
    return times


def bench_shadowed_panel() -> None:
    print("Panel repaint cost: with vs. without QGraphicsDropShadowEffect")
    _report("shadowed", _bench_shadowed_panel(shadowed=True))
    _report("unshadowed", _bench_shadowed_panel(shadowed=False))
```

(needs `from PySide6.QtGui import QColor` added to the file's imports, and
a call to `bench_shadowed_panel()` added in `main()`). Run it before and
after Step 1 — the "shadowed" number is expected to dwarf "unshadowed,"
and that delta is your evidence this was the actual bottleneck rather than
a plausible-sounding guess. If the gap turns out smaller than expected,
that's useful too: it means there's a second contributor still to find,
and this benchmark stays in the suite either way as a regression guard.

**Not yet ruled out, lower priority to check next if Step 1 doesn't close
the gap to 60fps on its own:** the app-wide mouse-move `eventFilter` in
`main_window.py` (confirmed still present) feeds `OceanBackgroundWidget`
parallax on every mouse move anywhere in the app, at 30fps ticker cadence
— cheap per the Root Cause A fix, but worth a `cProfile` pass with the
actual Debugging Buddy screen active and a real crash log streaming in, to
catch anything screen-specific `profile_effects.py`'s isolated benchmarks
wouldn't see (e.g., `debugging.py`'s own paint work while `_on_chunk`
appends text at whatever rate the AI provider streams tokens).

---

## Priority 2 — Visual progress feedback (Debugging Buddy)

### What's already built and working

`ui/widgets/progress_trail.py`'s `ProgressTrail` is a finished, tested
widget purpose-built for exactly this ask: a small hideable list that
appends plain-language step descriptions ("Running EditMode tests…")
rather than a fabricated percentage bar. `ui/thread_utils.py`'s
`launch_worker` already wires it up generically:

```python
# thread_utils.py, lines 39-77 (confirmed current)
def launch_worker(
    owner: Any,
    worker: QObject,
    *,
    progress_slot: Callable[[str], None] | None = None,
) -> QThread:
    ...
    if progress_slot is not None and hasattr(worker, "progress"):
        worker.progress.connect(progress_slot)
    ...
```

— if a worker declares a `progress = Signal(str)`, passing
`progress_slot=trail.add_step` connects it automatically; if it doesn't,
this is a silent no-op. Nothing here needs to change.

### The gap

It's wired into exactly one place: `_ProjectHealthScanWorker` (a
project-wide naming/dead-reference scan), which is not the flagship flow.
The actual "paste a crash log, get an AI-written fix" flow — the thing
Spiced is being positioned around — has no step feedback at all:

```python
# debugging.py, line 124 — the flagship worker, no progress signal
class _CrashWorker(AIStreamWorker):
    def __init__(self, services, log_text, source_type, source_filename):
        super().__init__()
        ...

    def _call(self, on_chunk):
        provider = self._services.build_provider()
        project = self._services.active_project()
        team_mode = self._services.team_mode_enabled()
        analysis = self._services.debugging.analyze(
            provider, self._log_text, project=project,
            source_type=self._source_type, source_filename=self._source_filename,
            record_usage=self._services.usage.record_prompt,
            team_mode=team_mode,
            team_members=self._services.team_prompt_context(project) if team_mode else None,
            on_chunk=on_chunk,
        )
        ...
```

```python
# debugging.py, lines 1717-1738 — _on_analyze, no ProgressTrail
def _on_analyze(self) -> None:
    ...
    self._set_busy(True)
    self._result.clear()
    worker = _CrashWorker(self._services, log_text, source_type, filename)
    thread = launch_worker(self, worker)
    thread.started.connect(worker.run)
    worker.chunk.connect(self._on_chunk)
    worker.done.connect(self._on_done)
    worker.failed.connect(self._on_failed)
    worker.done.connect(thread.quit)
    worker.failed.connect(thread.quit)
    thread.start()
```

So today the only visible feedback before AI text starts streaming in is
the button switching to "Analyzing…" with a `water_fill` animation — an
indeterminate spinner in slightly nicer clothes. Once the AI call starts
streaming, `_on_chunk` gives real per-token feedback, so the actual gap is
narrower than it first looks: it's specifically the pre-stream phase
(reading the log, building the excerpt/prompt, resolving the provider,
opening the connection) that has nothing.

### Fix

Add a `progress` signal to `_CrashWorker` and emit a small number of real
steps around the actual work `_call` already does — no fabricated
percentages, consistent with `ProgressTrail`'s own stated design
principle:

```python
# debugging.py — _CrashWorker
class _CrashWorker(AIStreamWorker):
    progress = Signal(str)   # Signal is already imported for AIStreamWorker's own use

    def __init__(self, services, log_text, source_type, source_filename):
        super().__init__()
        self._services = services
        self._log_text = log_text
        self._source_type = source_type
        self._source_filename = source_filename

    def _call(self, on_chunk):
        self.progress.emit("Reading the log…")
        provider = self._services.build_provider()
        project = self._services.active_project()
        team_mode = self._services.team_mode_enabled()
        self.progress.emit(f"Contacting {provider.name}…")  # or however provider exposes a display name — check core.providers
        analysis = self._services.debugging.analyze(
            provider, self._log_text, project=project,
            source_type=self._source_type, source_filename=self._source_filename,
            record_usage=self._services.usage.record_prompt,
            team_mode=team_mode,
            team_members=self._services.team_prompt_context(project) if team_mode else None,
            on_chunk=on_chunk,
        )
        ...
        return analysis
```

Then in the screen: add a `ProgressTrail` near the Analyze button/result
area (constructor, alongside wherever `self._analyze_btn` is built), reset
it at the start of each run, and pass it through `launch_worker`:

```python
# debugging.py — wherever self._analyze_btn / self._result are constructed
self._analysis_progress_trail = ProgressTrail()
layout.addWidget(self._analysis_progress_trail)   # placement: between the button and self._result reads well

# _on_analyze
def _on_analyze(self) -> None:
    ...
    self._set_busy(True)
    self._result.clear()
    self._analysis_progress_trail.reset()
    worker = _CrashWorker(self._services, log_text, source_type, filename)
    thread = launch_worker(self, worker, progress_slot=self._analysis_progress_trail.add_step)
    ...
```

Check `_call`'s exact provider-name attribute against `core/providers.py`
before using `provider.name` verbatim above — the point is the pattern,
confirm the exact field.

Once this lands and looks right on Debugging Buddy, `_VersionCheckWorker`,
`_CodeHealthWorker`, `_ChangelogWorker`, and the other `AIStreamWorker`
subclasses in this file are all one-line-per-worker away from the same
treatment — same `progress = Signal(str)` + a couple of `emit()` calls,
since `launch_worker`'s `hasattr` check means nothing else has to change.
Given the Unity-debugging-software positioning for this alpha, Debugging
Buddy is the one that should ship with this; the rest can follow post-alpha
without it reading as an inconsistency, since users won't be comparing two
AI-call screens side by side in the same session as often as they'll use
Debugging Buddy repeatedly.

---

## Priority 3 — Unity setup, beyond what's already shipped

`SETUP_SIMPLIFICATION_SPEC.md`'s Findings 1–3 covered the general
engine-agnostic friction (engine chosen before folder seen, no executable
auto-discovery, no installer) and are shipped. Positioning this alpha
specifically as *Unity* debugging software raises the bar on "easier than
its competitors" specifically for Unity. This section replaces the earlier,
lighter-weight version of Priority 3 with concrete build items, grounded in
a competitive scan of how Sentry, BugSplat, Bugnet, Jahro, LoopKit,
Regression Games, and modl:test each handle Unity debugging (full writeup:
`UNITY_DEBUGGING_COMPETITIVE_RESEARCH.md`, delivered separately). Two
findings from that scan matter for how these are scoped:

- **Spiced's real edge is zero SDK integration** — every competitor above
  requires the developer to import a package or wire a partial class into
  their Unity project *before* a bug happens. Spiced reads a log file that
  already exists. Nothing below should be built in a way that costs this —
  no new build-time dependency in the user's Unity project, ever.
- **The one capability gap nobody in that market closes without an SDK is
  connecting an error to what led up to it.** LoopKit and Sentry Session
  Replay both do this by capturing live. Items 3a and 3c below get most of
  that value from data that already exists on disk or in Spiced's own
  history, with no live capture and no new integration.

### 3a. One-click Editor.log import (setup-friction fix, do this first)

Confirmed gap: `debugging.py`'s only ways to get a log in are pasting or
`_import_file()`'s manual file-picker (lines 1701–1715) — the user has to
know Unity even writes an `Editor.log`, then go find it themselves. Unity
writes it to a fixed, well-known path per OS:

- Windows: `%LOCALAPPDATA%\Unity\Editor\Editor.log`
- macOS: `~/Library/Logs/Unity/Editor.log`
- Linux: `~/.config/unity3d/Editor.log`

Add a function alongside the existing engine-executable resolvers in
`core/engine_executable_resolve.py` (same file that already does
OS-specific discovery for Godot/Unreal, so this fits the existing pattern
rather than introducing a new module):

```python
# core/engine_executable_resolve.py
import os
import platform
from pathlib import Path


def find_unity_editor_log() -> Path | None:
    """The current user's live Unity Editor.log, if it exists on this OS."""
    system = platform.system()
    if system == "Windows":
        base = os.environ.get("LOCALAPPDATA")
        candidate = Path(base) / "Unity" / "Editor" / "Editor.log" if base else None
    elif system == "Darwin":
        candidate = Path.home() / "Library" / "Logs" / "Unity" / "Editor.log"
    else:
        candidate = Path.home() / ".config" / "unity3d" / "Editor.log"
    return candidate if candidate and candidate.is_file() else None
```

Wire it into `debugging.py` next to the existing import button (line
608–616): add a second `PillButton("Import latest Editor.log")` beside
`self._import_btn`, enabled only when `find_unity_editor_log()` returns a
path and the active project's engine is Unity (reuse whatever
`core/engine_dispatch.py` already exposes for "this project's engine" —
confirmed shipped from the setup-simplification work). Clicking it does
what `_import_file()` already does (`Path(path).read_text(...)` into
`self._log_input`, set `self._pending_filename`) — same code path, just a
different, pre-resolved source path instead of a file dialog. This is the
smallest, most self-contained item in this whole document and the most
directly comparable to what a Unity-only competitor would be judged
against, so it's worth shipping alone if nothing else in 3b/3c lands before
alpha.

### 3b. "Leading up to this" excerpt — new, not a reuse of the existing excerpt

Confirmed via `core/unity_log_parser.py`: today's `parse_unity_log` only
keeps lines that match an exception header, a stack frame, or a compiler
error (`_EXCEPTION_RE`, `_FRAME_RE`, `_COMPILER_RE`) — every other Console
line is discarded, including whatever the developer's own `Debug.Log` calls
printed right before the crash. That's a deliberate, reasonable design for
building the AI prompt (it keeps the excerpt small and structured), but it
also means the current excerpt genuinely cannot answer "what happened right
before this" — that context is thrown away, not just unsurfaced.

This is additive, not a change to the existing parser (nothing about
`_build_excerpt`'s prompt-facing behavior should change): add a second,
separate function that, given the *raw* log text and the byte/line offset
of the first matched error, slices a fixed window of whatever Console lines
came immediately before it — independent of whether those lines match any
of the three regexes:

```python
# core/unity_log_parser.py — new function, alongside parse_unity_log
LEADING_CONTEXT_LINES = 12


def leading_context(text: str, first_error_line_index: int) -> list[str]:
    """The plain Console lines immediately before the first detected error,
    verbatim -- deliberately not filtered through the exception/compiler
    regexes above, since the point is showing what was happening generally,
    not extracting another structured error."""
    lines = text.splitlines()
    start = max(0, first_error_line_index - LEADING_CONTEXT_LINES)
    return [line for line in lines[start:first_error_line_index] if line.strip()]
```

`parse_unity_log` doesn't currently track *which line number* the first
match came from (it iterates `lines` without an enumerate index) — that's
the one real change needed to the existing function: switch its `for raw in
lines:` loop to `for i, raw in enumerate(lines):` and record the index of
the first `commit()` call as `ParsedLog.first_error_line_index: int | None`
(new field, default `None` when `has_errors` is false). `DebuggingService.parse()`
(debugging.py line 47) stays a one-line call as-is.

Surface it in the UI as its own small, collapsed section between
`self._log_input` and the `Analyze` row (debugging.py, around line 607) —
reuse `SourceLinkExpander` (already used for the regression-match/excerpt
disclosure at line 631) rather than introducing a new widget, so it reads
as the same "show me the evidence" interaction language already established
on this screen: `SourceLinkExpander("What was happening before this", "\n".join(leading_context(...)))`,
populated once a log is pasted/imported and before the user even clicks
Analyze, since it's a local parse with no AI call involved.

### 3c. Repeat-offender signal — correction to the earlier research write-up

The research doc's original framing of this as a from-scratch build was
wrong in one respect, caught while grounding this spec against the actual
code: **most of this already exists.** `core/regression.py`'s
`RegressionService` already fingerprints every debug session by an
`(error_type, location)` signature, matches new ones against history
(exact or fuzzy-by-title), and `debugging.py`'s `_on_done` (line
1743–1754) already surfaces it — "Matches an already-tracked open issue…"
or "Resembles \"X\", marked resolved on…" is appended to the result text
and shown in the source-link description today. There's no gap to close
there.

The real, narrower gap: that mechanism matches *the same bug* recurring. It
doesn't answer a different, also-useful question — "which script keeps
showing up across *different* bugs in this project" (a hotspot, not a
repeat). That's a distinct aggregation over the same data
`DebugSessionRepository.list_for_project()` already returns
(`storage/debug_sessions.py` line 86), grouping by `detected_file` across
however many sessions instead of matching one signature at a time:

```python
# core/debugging.py — new method on DebuggingService, alongside history()
from collections import Counter

def hotspots(self, project_id: int, limit: int = 3, min_occurrences: int = 3) -> list[tuple[str, int]]:
    """Scripts that have shown up in several *different* past analyses for
    this project -- a repeat-offender signal, distinct from RegressionService's
    same-bug-recurring match. Purely local aggregation over already-stored
    sessions; no new data collection."""
    sessions = self._sessions.list_for_project(project_id, limit=200)
    counts = Counter(s.detected_file for s in sessions if s.detected_file)
    return [
        (name, count)
        for name, count in counts.most_common(limit)
        if count >= min_occurrences
    ]
```

Surface this as a single quiet line above the "Recent sessions" history box
(debugging.py, line 634) when it returns anything —
`"HealthPickup.cs has come up in 4 of your last past analyses — might be worth a closer look."`
— shown once per project per app session (not on every keystroke), not as
a blocking warning. This is a small, honest addition on top of the existing
regression infrastructure, not new infrastructure of its own.

### 3d. Live Editor.log tailing — flagged as a real design-principle tension, not a clean recommendation

The research doc's live-tail idea ("prompt the user the moment an error
appears") is worth naming here because it's genuinely different from 3a–3c:
it needs a background file-watcher polling or watching `Editor.log` while
Spiced is open. That directly contradicts a design principle stated
explicitly elsewhere in this same screen — `debugging.py`'s Auto-Generated
Unit Tests + Docs intro text says, for both Unity and Unreal, regeneration
happens "only when you click the button below — never a background
file-watcher" (lines 1088–1104). That line wasn't written about this
feature, but the principle it states — Spiced does work when asked, not
continuously in the background — is a real product stance, and a live
Editor.log tail would be the first exception to it.

This isn't a reason to rule it out — the case for it (surfacing help the
moment an error appears, rather than waiting for the developer to remember
Spiced exists) is genuinely strong for the "easier than competitors"
positioning — but it's a product decision to make deliberately, not a
straightforward extension of 3a like it first appears. If it's wanted,
scope it as opt-in (a toggle, off by default) rather than silently changing
existing behavior, and say so in the UI copy so it doesn't read as a
contradiction to users who've noticed the "never a background file-watcher"
language elsewhere in the app. Recommend deferring this one past alpha
unless Lauren decides the positioning value is worth being the first
feature to cross that line.

### 3e. First-run empty state should name Unity by name

Smaller polish item, still worth doing alongside 3a: the placeholder text
at debugging.py line 602–604 ("Paste your Unity console output or
Editor.log excerpt here…") already says Unity, but worth auditing the rest
of this screen's empty/placeholder copy the same pass — cheap, and it's
exactly the kind of detail a Unity-specific competitor comparison would
notice.

---

## Suggested order

1. Priority 1, Step 1 (one-line fix, biggest win, verify with the new
   benchmark) — do this first, it's cheap and it's the actual ask.
2. Priority 2 (self-contained, ~20 lines across two files, no risk to
   anything else).
3. Priority 3a (one-click Editor.log import) — smallest, most visible
   competitive-parity win, ship this before alpha regardless of what else
   makes the cut.
4. Priority 3b (leading-up-to excerpt) and 3c (repeat-offender signal) —
   both additive, both build on data/infrastructure that already exists,
   good candidates for the same pass since they touch the same screen.
5. Priority 1, Step 2 (visual-parity shadow replacement) if Step 1's
   before/after benchmark shows the shadow removal is visually missed —
   otherwise skip it, don't add complexity back for a look nobody notices
   is gone.
6. Priority 3e (empty-state copy audit) — bundle into whichever of the
   above pass touches this screen last.
7. Priority 3d (live Editor.log tailing) — explicitly held for a deliberate
   decision, not scheduled as part of this alpha pass by default.
