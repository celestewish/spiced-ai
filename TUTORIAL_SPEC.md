# In-App Tutorial Spec

Scope: a first-launch, in-app walkthrough that teaches Spiced by having the
user actually run a crash analysis on a bundled demo project, then prompts
them to connect their own. Grounded in two things checked against the real
codebase: `core/demo_data.py`'s `DemoDataService` (already built, currently
unwired to any UI) and UX research on what makes onboarding work versus what
makes people tune it out (sources at the bottom).

## Design principles this spec follows, and why

Nielsen Norman Group's research on this exact question is unambiguous on one
point: mandatory "push" tutorials that block the app before first use don't
improve task performance and actively hurt usability — people resist the
interruption, and information shown out of context doesn't stick. Their
recommended alternative for a genuinely new, unfamiliar workflow is an
**interactive walkthrough where users learn by doing in a low-stakes
environment**. That's the whole shape of this spec: the "low-stakes
environment" is the demo project, and "learn by doing" means the user
clicks the real Analyze button and gets a real (if mock) result, not a
tooltip describing what the button does.

Two more findings shape specific decisions below. NN/G separately warns
against "deck-of-cards" tutorials that try to explain everything and end up
oversimplifying, straining memory, and boring people on things they'd have
figured out anyway — their guidance is to skip explaining standard UI and
only teach what's genuinely non-obvious. And the practitioner side (Userpilot's
analysis of why long tours fail, backed by a case study that tripled
activation by cutting a tutorial down to one real task) argues for routing
to one task and getting to a genuine first success moment in as few steps
as possible, rather than touring feature-by-feature. Both point the same
direction for Spiced: **don't tour all 14 screens.** Cover one task — running
a crash analysis, since Debugging Buddy is the flagship this alpha is being
positioned around — end to end, then stop.

Concretely, this means: no separate onboarding wizard screen, no walking
through Testing/Feedback/Marketing/Business/etc. at all, a persistent Skip
button on every step (NN/G: guidance must be easy to dismiss), and a way to
bring it back later from Settings (NN/G: also easy to *recall* — skip isn't
the same as delete).

## What already exists and needs no new code

`core/demo_data.py`'s `DemoDataService` — exposed as `Services.demo` (already
wired, `main_window.py` line 212: `self.demo = DemoDataService(self.db)`,
confirmed on the current `Services` class) — already seeds a safe, realistic,
repeat-safe demo project (`DEMO_PROJECT_NAME = "Starfall Prototype (Demo)"`)
with a pre-completed debug session (a `NullReferenceException` in
`HealthPickup.cs:24`, clearly labeled `provider="Sample data (no AI used)"`),
mixed-status test cases, a test run, and a feedback batch. `DemoDataService.seed()`
is a no-op if the demo project already exists, and `load_fresh_demo()` resets
it — both usable as-is.

`ai/mock_provider.py`'s `MockProvider` is a complete, always-available
provider (`is_available()` returns `True` unconditionally) that needs no API
key and runs the exact same `DebuggingService.analyze()` code path as a real
provider, including real chunk-by-chunk streaming (`generate_stream`). This
is the piece that makes "learn by doing" possible on a first launch, before
the user has entered any API key: the tutorial's live analysis step uses
`MockProvider()` directly rather than `self._services.build_provider()`, so
it works with zero setup and never silently touches the user's own provider
setting in Settings.

## New: a first-run flag

Follow the exact pattern already used for accessibility settings
(`services.py`, `ACCESSIBILITY_REDUCE_MOTION_KEY` /
`accessibility_reduce_motion_enabled()` / `set_accessibility_reduce_motion_enabled()`)
and widget preferences (`WIDGET_PREFERENCES_KEY`) — both thin wrappers over
`SettingsRepository`'s plain key/value store (`storage/settings.py`):

```python
# app/services.py — new key + accessor pair, alongside the existing ones
TUTORIAL_COMPLETED_KEY = "tutorial_completed"

def tutorial_completed(self) -> bool:
    return self._settings.get(TUTORIAL_COMPLETED_KEY, "") == "1"

def set_tutorial_completed(self, completed: bool) -> None:
    self._settings.set(TUTORIAL_COMPLETED_KEY, "1" if completed else "")
```

This is the only new persistence needed. No new table, no new repository.

## New module: `ui/tutorial/tutorial_overlay.py`

Nothing in the current codebase highlights a live widget in place while
dimming the rest of the screen — `ShortcutsCheatSheet` (`ui/shortcuts_cheatsheet.py`)
is a plain modal dialog, and `ProgressTrail`/`SourceLinkExpander` are inline
disclosure widgets. This is genuinely new UI, and it needs to be built
carefully given what Priority 1 of `UNITY_ALPHA_READINESS_SPEC.md` just
fixed: `_apply_glass_elevation()`'s `QGraphicsDropShadowEffect` was forcing a
full-subtree offscreen rasterize on every repaint of the screen it sat on,
and that was the app's actual framerate bug. A full-window tutorial overlay
is the same shape of risk if built the same way. So, explicitly:

**It must look like it belongs to Spiced, not like a third-party tour
plugin bolted on top.** Concretely: the callout box gets `setObjectName("Panel")`
— the exact same one-liner `ShortcutsCheatSheet` already uses (line 31 of
`ui/shortcuts_cheatsheet.py`) to inherit `theme.py`'s existing `QDialog#Panel`
QSS rule (line 452: `CREAM_PANEL` background, `CARD_BORDER`, 20px rounded
corners) rather than hand-rolled colors. Its title label gets
`setObjectName("SectionTitle")` (theme.py line 735, already used everywhere
else for a section heading — `BROWN_SOFT`, bold, one size down from body
text) so it reads as one more Spiced panel, not a foreign overlay. Its
Next/Skip buttons are `PillButton` — `Next` a normal filled pill, `Skip`
`PillButton(..., ghost=True)` — exactly the button component and the
primary/ghost distinction the rest of the app already uses (see
`ShortcutsCheatSheet`'s own `Close` button, line 46, for the precedent).
None of this is new styling to invent; it's reusing what's already in
`theme.py` and `ui/widgets/pill_button.py` so a screenshot of a tutorial
step is indistinguishable in style from a screenshot of any other Spiced
dialog.

The dim scrim behind the cutout should read as "glass chrome," not a
generic dark rectangle: pull its color from `theme.resolve_palette()`
rather than a made-up `QColor` — the existing `DARK_PANEL_BG`/`SIDEBAR`
family (the same dark purple-toward-magenta gradient tones the sidebar and
top bar already use, theme.py lines 84 and 121) is the app's own established
"dim, translucent chrome" language, so the scrim should sample from that
family (a flat, semi-transparent fill is fine — the panels it's imitating
already use gradients, but a moving cutout repainting a full gradient
every step is unnecessary cost for no visible gain). In high-contrast mode
(`Services.accessibility_high_contrast_enabled()`, already plumbed through
`resolve_palette(high_contrast=..., colorblind_safe=...)`), the scrim should
become a flat, fully opaque fill instead of anything translucent — this
matches `theme.py`'s own stated principle for that mode (module docstring,
lines 30-35: "translucency and a photographic sunset backdrop would
undermine the whole point of this mode... every panel/card background
resolves to a flat, opaque value"). The overlay should call
`resolve_palette()` itself rather than hard-coding a color, so it stays in
sync automatically if the palette ever changes.

- **No `QGraphicsEffect` of any kind.** The overlay is a plain `QWidget`
  covering `MainWindow`'s full `rect()`, with a custom `paintEvent` that
  paints a semi-transparent dim color everywhere except a cutout rectangle
  around the current step's target widget, plus a small callout box (title,
  body text, Next/Skip buttons) positioned next to the cutout.
- **It repaints on step change and on resize — never on a timer, never
  per-frame.** There is no animation loop here; showing/hiding and moving
  the cutout are one-shot `update()` calls, not a `Ticker`-driven tick like
  `OceanBackgroundWidget`'s. This keeps it structurally unable to reintroduce
  the class of bug Priority 1 just fixed.
- **Respects `accessibility_reduce_motion_enabled()`** (already on `Services`,
  used elsewhere for exactly this purpose) — with it on, skip any fade
  in/out on step transitions and just show/hide instantly. There's no
  motion to reduce otherwise, since this overlay was never animated to
  begin with.

```python
# ui/tutorial/tutorial_overlay.py — new file
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from spiced.ui import theme
from spiced.ui.widgets.pill_button import PillButton

# The scrim samples the same dark glass-chrome family as the sidebar/top bar
# (theme.SIDEBAR / DARK_PANEL_BG) rather than an arbitrary color -- see
# TUTORIAL_SPEC.md's "New module" section for why. A flat fill, not that
# family's gradient: cheap to repaint on step change, and the cutout moving
# across a gradient buys nothing visually a flat tone doesn't already give.
_SCRIM_RGBA = QColor(43, 28, 70, 170)  # theme.SIDEBAR (#2B1C46) at ~67% alpha
_SCRIM_HIGH_CONTRAST = QColor(0, 0, 0, 255)  # flat/opaque -- theme.py's own
# high-contrast principle (module docstring): no translucency in this mode.


@dataclass
class TutorialStep:
    title: str
    body: str
    target: Callable[[], QWidget | None]  # resolved fresh each time the step is shown
    on_enter: Callable[[], None] | None = None  # e.g. pre-fill the log input
    # When set, the step auto-advances on this signal instead of waiting for
    # "Next" -- used for the "click Analyze, then wait for the real result"
    # step so the user's own click, not a button in this overlay, is what
    # drives progress (see the flow section below for why that matters).
    auto_advance_signal: object | None = None


class TutorialOverlay(QWidget):
    """Dims MainWindow, cuts a hole around the current step's target widget,
    and shows a small callout beside it. Repaints only on step change/resize
    -- see the module's governing spec (TUTORIAL_SPEC.md) for why this must
    never become a QGraphicsEffect or a per-frame-ticked animation."""

    def __init__(self, main_window: QWidget, services) -> None:
        super().__init__(main_window)
        self._main_window = main_window
        self._services = services
        self._steps: list[TutorialStep] = []
        self._index = 0
        self._on_finished: Callable[[], None] | None = None

        # setObjectName("Panel") is the same one-liner ShortcutsCheatSheet
        # already uses (ui/shortcuts_cheatsheet.py line 31) to pick up
        # theme.py's QDialog#Panel rule (CREAM_PANEL background, CARD_BORDER,
        # 20px rounded corners) instead of inventing new panel styling here.
        self._callout = QWidget(self)
        self._callout.setObjectName("Panel")
        callout_layout = QVBoxLayout(self._callout)
        self._title_label = QLabel()
        self._title_label.setObjectName("SectionTitle")  # theme.py line 735
        self._body_label = QLabel()
        self._body_label.setWordWrap(True)
        callout_layout.addWidget(self._title_label)
        callout_layout.addWidget(self._body_label)
        buttons = QHBoxLayout()
        self._skip_btn = PillButton("Skip", ghost=True)
        self._skip_btn.clicked.connect(self.finish)
        self._next_btn = PillButton("Next")
        self._next_btn.clicked.connect(self._advance)
        buttons.addWidget(self._skip_btn)
        buttons.addStretch(1)
        buttons.addWidget(self._next_btn)
        callout_layout.addLayout(buttons)

    def start(self, steps: list[TutorialStep], on_finished: Callable[[], None]) -> None:
        self._steps = steps
        self._index = 0
        self._on_finished = on_finished
        self.setGeometry(self._main_window.rect())
        self.show()
        self.raise_()
        self._show_step()

    def _show_step(self) -> None:
        step = self._steps[self._index]
        self._title_label.setText(step.title)
        self._body_label.setText(step.body)
        self._next_btn.setVisible(step.auto_advance_signal is None)
        if step.on_enter is not None:
            step.on_enter()
        if step.auto_advance_signal is not None:
            step.auto_advance_signal.connect(self._advance)
        self.update()

    def _advance(self) -> None:
        self._index += 1
        if self._index >= len(self._steps):
            self.finish()
            return
        self._show_step()

    def finish(self) -> None:
        self.hide()
        if self._on_finished is not None:
            self._on_finished()

    def paintEvent(self, event) -> None:  # noqa: N802 (Qt override)
        if not self._steps:
            return
        target = self._steps[self._index].target()
        painter = QPainter(self)
        scrim = (
            _SCRIM_HIGH_CONTRAST
            if self._services.accessibility_high_contrast_enabled()
            else _SCRIM_RGBA
        )
        painter.fillRect(self.rect(), scrim)
        if target is not None and target.isVisible():
            top_left = target.mapTo(self._main_window, target.rect().topLeft())
            cutout = QRect(top_left, target.size())
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
            painter.fillRect(cutout, Qt.GlobalColor.transparent)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
            self._position_callout(cutout)
        painter.end()

    def _position_callout(self, cutout: QRect) -> None:
        self._callout.adjustSize()
        x = min(cutout.left(), self.width() - self._callout.width() - 16)
        y = cutout.bottom() + 12
        if y + self._callout.height() > self.height():
            y = max(0, cutout.top() - self._callout.height() - 12)
        self._callout.move(max(16, x), y)
        self._callout.show()

    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        self.update()
```

(Sketch, not final pixel-perfect layout/spacing — but the styling hooks
above, `objectName("Panel")`/`objectName("SectionTitle")`/`PillButton`, are
the real mechanism, not a placeholder: they're what makes this pick up
`theme.py`'s actual QSS automatically, including text size, high-contrast,
and colorblind-safe variants, since `build_stylesheet()` is applied once at
the app level and every widget with these object names already restyles
itself when that stylesheet changes — the overlay needs no accessibility
logic of its own beyond the scrim color swap above.)

## The flow

Everything below lives on `DebuggingScreen` (`ui/screens/debugging.py`) and
`MainWindow` — no other screen is touched, per the "one task, not a tour"
principle above.

1. **Trigger.** In `MainWindow.__init__`, right after `self._apply_glass_elevation()`
   (line 219), add:

   ```python
   if not self._services.tutorial_completed():
       QTimer.singleShot(0, self._start_tutorial)
   ```

   `QTimer.singleShot(0, ...)` defers the start until after the window is
   shown and laid out — the overlay needs real widget geometries from
   `mapTo()`, which aren't valid before the first show. `_start_tutorial()`
   constructs `TutorialOverlay(self, self._services)` — the `services`
   argument is what lets the overlay read `accessibility_high_contrast_enabled()`
   for the scrim color above, matching how every other accessibility-aware
   piece of this app (e.g. `background_scene.py`'s `_FakeServices`-driven
   checks) takes `Services` rather than duplicating settings reads.

2. **Seed and switch.** `_start_tutorial()` calls `self._services.demo.seed()`
   (a no-op if already seeded — safe to call unconditionally), sets it as
   the active project via whatever `ProjectsService`/`Services` method the
   rest of the app already uses for project switching (reuse, don't
   duplicate), and switches `self._stack` to the Debugging Buddy index
   (`self._stack.setCurrentIndex(NAV_ITEMS.index("Debugging Buddy"))`).

3. **Steps**, each targeting a widget `debugging.py` already builds and
   names (all confirmed to exist at their cited lines):

   - **Welcome** — target: the Debugging Buddy nav button
     (`self._nav_buttons[NAV_ITEMS.index("Debugging Buddy")]` in
     `main_window.py`). "This is Debugging Buddy — Spiced's crash analyzer.
     We've loaded a sample project so you can try a real analysis safely."
   - **The log input** — target: `self._log_input` (debugging.py line 601).
     `on_enter` pre-fills it with the same excerpt `demo_data.py` already
     uses for its seeded session (`HealthPickup.cs:24` NullReferenceException)
     via a small shared constant so the two don't drift, so the live
     analysis and the "Recent sessions" example tell the same story.
     "Here's a real crash log — go ahead and click Analyze."
   - **Analyze** — target: `self._analyze_btn` (line 613).
     `auto_advance_signal` is a new `Signal` this step connects to that fires
     once the worker's `done` fires (see below) — the user's own click drives
     the tutorial forward, not a "Next" button, which is the actual "doing"
     part of "learn by doing." This step's click must run through
     `MockProvider()` rather than `self._services.build_provider()` — smallest
     change is a tutorial-mode flag threaded into `_on_analyze()`'s worker
     construction (`_CrashWorker` already takes `services`; give it an
     optional `provider_override` param defaulting to `None`, used only when
     set).
   - **Progress feedback** — target: `self._analysis_progress_trail` (line
     652, confirmed shipped by the Priority 2 work). "Watch the steps here
     while it works." Shown while the worker is running, auto-advances on
     the same `done` signal as the Analyze step (or is folded into it as one
     step — implementer's call, both target widgets are adjacent).
   - **The result** — target: `self._result` (line 622). "Here's the
     explanation and next steps, plain-language, no jargon."
   - **Full transparency** — target: `self._source_link` /
     `self._leading_context_expander` (lines 631, 629 — confirmed shipped by
     Priority 3b). "Expand this anytime to see exactly what was sent and
     what was happening right before the crash."
   - **Finish, and hand off** — no target (a centered `QDialog`, not an
     overlay callout, since there's no widget left to point at). Give it
     `setObjectName("Panel")` too, same as the step callout and same as
     `ShortcutsCheatSheet` (which is itself a `QDialog#Panel`) — it should
     look like the same dialog family, not a different one that only shows
     up once. "That's a real crash analysis, start to finish. Ready to
     connect your own Unity project?" with two buttons — "Connect a project"
     (switches to the Projects screen, already has the folder-first
     auto-detect flow from `SETUP_SIMPLIFICATION_SPEC.md`) and "Maybe later"
     (`PillButton(..., ghost=True)`, matching the Skip/Close ghost-button
     convention used everywhere else). Either choice calls
     `self._services.set_tutorial_completed(True)` — per NN/G, dismissing
     must be low-friction and must not be held hostage to finishing a step
     the user doesn't want right now.

4. **Skip, anytime.** The overlay's own Skip button (built into
   `TutorialOverlay`) calls `finish()` at any step, which should also set
   `tutorial_completed(True)` — skipping is not a "try again next launch,"
   it's a dismissal, consistent with NN/G's "must be easy to dismiss."

5. **Bring it back.** Add a "Replay tutorial" entry to Settings, next to the
   existing "Keyboard shortcuts" section (`settings.py`,
   `_build_keyboard_shortcuts_section`, line 676 — mirror this pattern for a
   new `_build_tutorial_section`). This calls the same `_start_tutorial()`
   flow regardless of the persisted flag, and re-seeds/reuses the demo
   project via `DemoDataService.seed()` (already idempotent). This is the
   "easy to recall later" half of NN/G's guidance — skipping shouldn't mean
   losing access to it forever.

## What this deliberately does not do

- **No tour of any other screen.** Testing, Feedback, Marketing, Business,
  Art, Audio, Animation, Shaders/VFX, Team, Roadmap, Settings all go
  untouched by this flow. If a future pass wants task-based walkthroughs for
  Testing or Feedback Review, they'd each get their own short, single-task
  flow reusing the same `TutorialOverlay` — not one long combined tour. The
  research above is specific that an 8+ step tour across many features
  under-performs several short, task-scoped ones.
- **No customization/preference-gathering step** (the "Customization"
  component NN/G's mobile-onboarding article separately identifies) — Spiced
  has no per-user settings that would make sense to collect before the user
  has seen the product at all, and forcing that up front is exactly the
  "deck-of-cards" pattern the research warns against.
- **No changes to `demo_data.py` or `mock_provider.py`** — both are used
  exactly as they already exist.

## Testing

Following this codebase's existing per-feature test-file convention (e.g.
`test_debugging_screen_editor_log_import.py`, `test_debugging_screen_hotspot.py`):

- `test_tutorial_overlay.py` — step advancement, skip-at-any-step, target
  resolution/cutout geometry math, reduce-motion behavior.
- `test_debugging_screen_tutorial_flow.py` — the Analyze step actually uses
  `MockProvider` when `provider_override` is set, doesn't touch the user's
  real `provider_name()` setting, and the auto-advance signal fires on the
  worker's real `done` signal.
- `test_services_tutorial_flag.py` — `tutorial_completed()`/
  `set_tutorial_completed()` round-trip through `SettingsRepository`, same
  shape as the existing `test_settings_screen.py` coverage for other flags.
- `test_main_window_construction.py` (existing file, extend) — confirm a
  fresh `Services(":memory:")` instance triggers the tutorial exactly once
  and a completed one doesn't re-trigger on construction.

## Sources

- [Onboarding Tutorials vs. Contextual Help — Nielsen Norman Group](https://www.nngroup.com/articles/onboarding-tutorials/)
- [Mobile-App Onboarding: An Analysis of Components and Techniques — Nielsen Norman Group](https://www.nngroup.com/articles/mobile-app-onboarding/)
- [Onboarding: Skip it When Possible — Nielsen Norman Group](https://www.nngroup.com/videos/onboarding-skip-it-when-possible/)
- [3 Types of Onboarding New Users — Nielsen Norman Group](https://www.nngroup.com/videos/onboarding-new-users/)
- [Why The Best Software Walkthroughs Don't Teach the Product — Userpilot](https://userpilot.com/blog/interactive-software-walkthroughs/)
- [How We Tripled User Activation With an Interactive Tutorial — DEV Community case study](https://dev.to/polliog/how-we-tripled-user-activation-with-an-interactive-tutorial-svelte-5-case-study-g33)
