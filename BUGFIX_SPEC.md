# Spiced Desktop — Bug Investigation & Fix Spec

Two reported bugs, root-caused against the actual codebase (`spiced-ai`, PySide6 desktop app + FastAPI `backend/`). Hand this to Claude Code as-is — it has file/line references for both.

---

## Bug 1 — WinError 10061 on Settings (notification routing/preferences), Roadmap changelog, and Roadmap suggestions

### Root cause

All three surfaces call the FastAPI `backend/` service over HTTP via `BackendClient` (`src/spiced/backend_client/api_client.py`). The base URL comes from `backend_client/config.py`:

```python
DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"

def backend_base_url() -> str:
    return os.environ.get("SPICED_BACKEND_URL", DEFAULT_BACKEND_URL).strip()
```

When nothing is listening on `127.0.0.1:8000` — i.e. the `backend/` FastAPI service (`uvicorn`) hasn't been started — every request raises a low-level `ConnectionRefusedError`, which Windows reports as `WinError 10061`. `httpx` wraps it as `httpx.ConnectError`, which `BackendClient._request` re-raises as:

```python
except httpx.HTTPError as exc:
    raise BackendAPIError(f"Could not reach the Spiced backend: {exc}") from exc
```

— and `str(exc)` includes the raw OS text, so `WinError 10061` ends up verbatim in the UI. This is caught and displayed (not a crash), but as an ugly, unexplained low-level string, in three places:

- **Roadmap → Changelog**: `ui/screens/roadmap.py:292-309` (`_refresh_changelog`), called from `RoadmapScreen.__init__` → `self.refresh()` (`roadmap.py:114`) — runs **unconditionally on screen construction**, regardless of whether Team Mode/Supabase is even configured.
- **Roadmap → Suggestions**: `ui/screens/roadmap.py:311-328` (`_refresh_suggestions`), same trigger.
- **Settings → notification routing/preferences panels**: `ui/screens/settings.py` (`_build_notification_routing_section` / `_build_notification_preferences_section`, refreshed around line 918-923) — gated on `auth.is_logged_in()` and an active team-linked project, so it only fires for a signed-in Team Mode user, but still has no check that the backend is actually reachable before calling.

### Why it happens in practice

`RoadmapService` / `TeamService` construct a bare `BackendClient()` with no reachability check anywhere in the call chain (`core/roadmap_service.py:16-19`, `core/team_service.py:32-40`). There's no distinction in the code between "Team Mode isn't configured" (which Settings/Roadmap do check via `auth.is_configured()` before letting you sign in) and "configured, but the backend process isn't running right now." The Roadmap screen's own docstring says viewing the changelog/suggestions "needs no login at all" and is "Backend-hosted so every developer sees the same list" (`roadmap_service.py:1-7`) — but it still unconditionally dials `127.0.0.1:8000`, which is a *local dev* default, not a shared/hosted one. So:

- If you're running the desktop app without the `backend/` service up (the common case for a solo dev not actively testing Team Mode), Roadmap tries and fails to reach it every single time you open that screen.
- If you *are* signed in to Team Mode but simply haven't started `uvicorn` yet in that session, Settings' notification panels fail the same way.

### Fix spec

1. **Translate the low-level error before it reaches the UI.** In `BackendClient._request` (`api_client.py:573-593`), catch connection-refused specifically (`httpx.ConnectError`, or inspect `exc.__cause__`/`isinstance(..., ConnectionRefusedError)`) and raise a distinct, friendly message, e.g.:
   `"Can't reach the Spiced backend at {base_url}. Is it running? See backend/README.md."`
   Keep the existing generic `BackendAPIError` message for other `httpx.HTTPError` cases (timeouts, DNS, etc. can keep more detail). Never let a raw `WinError`/OS errno string reach a `QLabel` or `QMessageBox`.

2. **Decide the actual product intent for Roadmap** (needs a product decision, not just code):
   - If there's a real hosted backend deployment for the public changelog/suggestions (so solo devs see it without running anything locally), point `DEFAULT_BACKEND_URL` — or a *separate* `SPICED_ROADMAP_URL`, decoupled from the Team Mode backend URL — at that hosted instance instead of `127.0.0.1:8000`.
   - If there's no hosted backend yet, don't auto-fire the network calls from `RoadmapScreen.__init__`. Either skip calling `refresh()` until the user explicitly asks, or show a calmer static message ("Roadmap needs a running Spiced backend — see docs") instead of attempting and failing a connection every time the screen opens.

3. **Add a one-time reachability check surfaced consistently**, rather than three screens independently discovering the same failure with slightly different copy. A small `BackendClient.ping()` (a cheap `GET /health` — check whether `backend/app/main.py` already exposes one, add if not) that `Services` can call once and cache, so Settings/Roadmap can short-circuit to the same friendly "backend unreachable" state instead of each making a live doomed request.

4. **Regression test**: extend `backend/tests/test_notifications.py` / add a desktop-side test that asserts `BackendClient._request` converts a connection-refused into the friendly message (mock `httpx.Client.request` to raise `httpx.ConnectError`), and that `RoadmapScreen._refresh_changelog` / `_refresh_suggestions` display that friendly text rather than the raw exception string.

---

## Bug 2 — Overall framerate

No single crash — this is an accumulation of continuous, uncapped repaint work. Root-caused with the repo's own profiling tool (`tools/profile_effects.py`, already checked in — it exists specifically to benchmark these exact widgets against a 16.6ms/frame budget, so use it to confirm before/after numbers rather than eyeballing it).

### Root cause A — `OceanBackgroundWidget` repaints the entire window at 60fps, always, everywhere

`src/spiced/ui/effects/background_scene.py`:

- `_TICK_INTERVAL_MS = 16` (`~60fps`, line 166) drives a single `Ticker` (`ui/effects/motion.py`) that calls `self.update()` on **every** tick (`_on_tick`, line 225-227), unconditionally, for as long as the app runs.
- This widget is the full-window backdrop behind *every one of the 14 screens* (`ui/main_window.py:143-146`, added first, `.lower()`'d, resized to `self.rect()` on every `resizeEvent`) — it's not scoped to the Dashboard, it paints continuously no matter which screen is active (Testing, Debugging, etc.), competing for CPU/GPU with whatever the user is actually doing.
- Each `paintEvent` (line 231-244) draws the cached sky/sun/island backdrop (good — that part's already cached, see the comment at line 186-189) **plus**, uncached, on every single 16ms tick: 3 wave layers each rebuilding a full `QPainterPath` from scratch via a Python `while` loop (`_wave_path`, line 451-481), 6 orbs with per-orb radial gradients, 3 wind-streak linear gradients, and 3 twinkle stars — none of this is clipped to `event.rect()` (the actually-exposed/dirty region); it always redraws the full widget size regardless of what's visible.
- **The ticker never pauses when the window is minimized, occluded, or not the active window.** Only `reduced_motion` (Settings toggle) and `accessibility_high_contrast_enabled` stop it (`refresh_accessibility_state`, line 197-215). A user who minimizes Spiced or alt-tabs away is still burning a full 60fps repaint cycle in the background indefinitely.
- `MainWindow` also installs an **application-wide mouse-move event filter** (`main_window.py:214-231`) that calls `self._background.set_mouse_norm(...)` → `self.update()` on *every mouse move anywhere in the app*, stacking additional repaints on top of the 16ms ticker while the user is actively working (dragging, hovering, scrolling any screen).

`tools/profile_effects.py`'s own `bench_ocean_background()` benchmarks exactly this at 920×600 / 1920×1080 / 2560×1440 — run it (`.venv\Scripts\python.exe tools\profile_effects.py`) to get current mean/p95 ms-per-frame numbers on the target machine before changing anything, then again after, since the tool's own docstring notes numbers are machine-relative.

### Root cause B — `PillButton` rebuilds a full offscreen pixmap (+ pixel-readback for ghost buttons) on every single paint

`src/spiced/ui/widgets/pill_button.py`, `paintEvent` (line 163-222): used at "~100 call sites across every screen" (per `ui/effects/motion.py`'s own docstring, line 49-50). On **every** repaint of **every** button instance:

1. Allocates a brand-new `QPixmap` sized to the button at device pixel ratio (line 171-173) — no reuse/caching across paints.
2. Renders the native style control into it (`style().drawControl`, line 178).
3. For `ghost=True` buttons, calls `buffer.toImage()` (line 240, inside `_sample_ghost_border_color`) — a full pixmap→image conversion — just to sample one pixel's color, redone from scratch every paint even though the theme/hover/checked state hasn't changed since the last frame.
4. Punches rounded corners via path subtraction + `CompositionMode_Clear`, then composites the result.

None of this is cached against "did anything about this button's appearance actually change since the last paint." A button that's merely a passenger in a larger repaint (e.g. sitting inside a screen that just got a `QGraphicsOpacityEffect` crossfade, or repainting because a parent frame's `QGraphicsDropShadowEffect` forced its subtree to re-rasterize — see Root cause C) redoes this full allocate → native-draw → clip → (maybe) pixel-readback → composite sequence for no visual change at all. `PillButton(water_fill=True)` additionally runs its *own* 16ms `Ticker` per loading instance (line 82, 123-124) — `tools/profile_effects.py`'s `bench_pill_button_concurrent()` already benchmarks 20 concurrent loading buttons for exactly this reason.

### Root cause C — `QGraphicsDropShadowEffect` on the frame that contains the entire screen stack

`ui/main_window.py:_apply_glass_elevation` (line 233-245) applies a `QGraphicsDropShadowEffect` to every `QFrame` found via `self.findChildren(QFrame)` (recursive) whose `objectName()` is in `{"Panel", "Sidebar", "ContextPanel", "TopBar"}`. `"Panel"` is the workspace frame built in `_build_workspace` (line 480-482) that directly contains `self._stack` — the `FadeStackedWidget` holding **all 14 screens** (Dashboard, Testing, Debugging, etc. — `testing.py` alone is 122KB of widgets). Any `QGraphicsEffect` forces Qt to rasterize the entire affected widget subtree offscreen before compositing the blur — confirm with the profiler whether this subtree's repaints are actually triggered as often as suspected (e.g. whenever a descendant widget calls `update()`, which can cascade), since this is the most speculative of the three root causes and worth verifying with `cProfile`/the existing `profile_worst_case()` pattern before assuming it's a live contributor.

### Fix spec

1. **Pause `OceanBackgroundWidget`'s ticker when it can't be seen.** Stop the `Ticker` (not just skip repainting) when the window is minimized (`QWidget.changeEvent` / `Qt.WindowState.WindowMinimized`) or not the active window, in addition to the existing reduced-motion/high-contrast checks in `refresh_accessibility_state`. Resume on restore/activate.
2. **Clip `paintEvent` to `event.rect()`** instead of unconditionally redrawing the full widget every tick — most ticks likely only need to update a small changed region (or none, if fully occluded by the panels above it).
3. **Cache the wave `QPainterPath` per layer per frame-period-bucket** instead of rebuilding it via a Python loop on every 16ms tick — e.g. precompute one period's path once and translate it via `QPainter.translate`/a `QTransform`, only regenerating on resize.
4. **Consider dropping the tick rate** for this specific decorative background (e.g. 30fps / 33ms instead of 60fps / 16ms) — halves the steady-state cost with a decorative, slow-moving scene where the difference won't be perceptible. Make it a named constant so it's easy to tune/measure.
5. **`PillButton`: cache the rendered pixmap** keyed on the inputs that actually affect its appearance (size, checked/hover/disabled state, theme palette, loading fraction bucket) and only redo the native-draw + corner-punch + ghost-border-sample when one of those actually changed, instead of on every paint. At minimum, sample the ghost border color once (construction time, and again on theme/state change) rather than via `toImage()` on every single frame.
6. **Re-scope or replace the `Panel` drop shadow.** Either move the shadow effect off the frame that contains the entire 14-screen stack (apply it to a thin static header/border widget instead, or paint a fixed shadow via a stylesheet/manual gradient rather than `QGraphicsEffect`), or confirm via profiling that it's not actually re-triggering on unrelated content changes before deciding it's worth the churn to change.
7. **Verify with the existing tool, not by feel.** Run `tools/profile_effects.py` before touching anything to get a baseline (all five benchmarks + the `cProfile` deep-dive), apply the fixes above incrementally, and re-run after each to confirm the mean/p95 per-frame numbers for `OceanBackgroundWidget` and `PillButton` actually drop and stay comfortably under the 16.6ms/frame (60fps) budget quoted in the tool's own docstring — remembering a real frame pays for every visible widget, not just one in isolation.

---

## Suggested order of work

1. Bug 1 fixes 1 and 3 (friendly error + shared reachability check) — small, isolated, immediately removes the raw WinError text regardless of the product decision in fix 2.
2. Bug 1 fix 2 — needs a product call from Lauren on whether Roadmap should hit a hosted backend; flag it rather than guessing.
3. Bug 2 fix 1 (pause ticker when hidden/minimized) — highest win-to-effort ratio, fixes background CPU burn even when Spiced isn't the focused app.
4. Bug 2 fixes 2-4 (Ocean background paint cost) and 5 (PillButton paint cost), profiling before/after each with `tools/profile_effects.py`.
5. Bug 2 fix 6 only after confirming with the profiler that the `Panel` shadow is a real contributor, not just a theoretical one.
