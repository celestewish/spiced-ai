"""Frame-cost profiling for ``ui.effects`` (and ``PillButton``, its main
consumer of ``ui.effects.motion.Ticker``).

Run with the repo venv from the repo root::

    .venv\\Scripts\\python.exe tools\\profile_effects.py

No display is required -- like ``tests/test_effects_*.py``, this forces
Qt's offscreen platform plugin before any Qt import. Every benchmark below
drives the real per-frame update path rather than timing construction or
teardown.

``QWidget.repaint()`` -- the pattern ``tests/test_effects_*.py`` uses for its
"paints without crashing" checks -- turns out to be a no-op under the
offscreen QPA platform: it defers to the platform's window-backingstore
flush, which offscreen never performs synchronously, so ``paintEvent`` never
actually runs (confirmed by instrumenting ``paintEvent`` directly: 0 calls
after ``repaint()``, still 0 after ``QTest.qWaitForWindowExposed``, even for
a top-level shown widget). ``QWidget.render(target_pixmap)`` instead calls
``paintEvent`` synchronously and directly, bypassing the backingstore
entirely, and does hit real ``paintEvent`` calls under offscreen -- so that's
what OceanBackgroundWidget's and PillButton's benchmarks below drive per
frame. FadeStackedWidget's and WaterSplashOverlay's benchmarks don't need
this workaround: their animations already go through ``update()`` +
``QApplication.processEvents()``, and plain ``update()`` (unlike
``repaint()``) does get processed by the normal event loop under offscreen.

Numbers vary by machine; treat this as a relative/regression tool (re-run
before and after a change to compare) more than an absolute spec. A 60fps
frame budget is 16.6ms -- anything comfortably under that per widget has
headroom to spare, since a real frame pays for every visible widget's
paint, not just one.
"""

from __future__ import annotations

import cProfile
import io
import os
import pstats
import statistics
import sys
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from spiced.ui.effects import motion  # noqa: E402
from spiced.ui.effects.background_scene import OceanBackgroundWidget  # noqa: E402
from spiced.ui.effects.splash import WaterSplashOverlay  # noqa: E402
from spiced.ui.effects.transitions import FadeStackedWidget  # noqa: E402
from spiced.ui.widgets.pill_button import PillButton  # noqa: E402

_app = QApplication.instance() or QApplication(sys.argv)


class _FakeServices:
    """Motion always on, high contrast always off -- the busiest real paint
    path each widget can be in, so these numbers are the worst case rather
    than the Reduce Motion resting state."""

    def accessibility_reduce_motion_enabled(self) -> bool:
        return False

    def accessibility_high_contrast_enabled(self) -> bool:
        return False


def _stats(times_ms: list[float]) -> tuple[float, float]:
    mean = statistics.mean(times_ms)
    p95 = statistics.quantiles(times_ms, n=100)[94] if len(times_ms) >= 20 else max(times_ms)
    return mean, p95


def _report(label: str, times_ms: list[float]) -> None:
    mean, p95 = _stats(times_ms)
    print(f"  {label:<28} mean={mean:7.4f}ms  p95={p95:7.4f}ms  n={len(times_ms)}")


# --- OceanBackgroundWidget ---------------------------------------------------

_OCEAN_SIZES: tuple[tuple[int, int], ...] = ((920, 600), (1920, 1080), (2560, 1440))
_OCEAN_ITERATIONS = 300


def _bench_ocean(width: int, height: int, iterations: int = _OCEAN_ITERATIONS) -> list[float]:
    parent = QWidget()
    widget = OceanBackgroundWidget(_FakeServices(), parent)
    parent.resize(width, height)
    parent.show()
    widget.resize(width, height)
    widget.set_mouse_norm(0.35, -0.2)
    target = QPixmap(width, height)

    for _ in range(5):  # warm up: first paints allocate gradients/paths
        widget._on_tick()
        widget.render(target)

    times: list[float] = []
    for _ in range(iterations):
        start = time.perf_counter()
        widget._on_tick()
        widget.render(target)
        times.append((time.perf_counter() - start) * 1000.0)

    parent.deleteLater()
    _app.processEvents()
    return times


def bench_ocean_background() -> None:
    print("OceanBackgroundWidget (_on_tick + repaint per frame)")
    for width, height in _OCEAN_SIZES:
        times = _bench_ocean(width, height)
        _report(f"{width}x{height}", times)


# --- PillButton(water_fill=True) --------------------------------------------

_PILL_ITERATIONS = 300
_PILL_CONCURRENT_COUNT = 20


def _make_loading_pill(parent: QWidget) -> PillButton:
    button = PillButton("Regenerate docs", parent, water_fill=True)
    button.resize(180, 44)
    button.show()
    button.set_loading(True)
    return button


def bench_pill_button_single() -> None:
    motion.set_active_services(_FakeServices())
    try:
        parent = QWidget()
        parent.resize(220, 80)
        parent.show()
        button = _make_loading_pill(parent)
        target = QPixmap(button.size())

        for _ in range(5):
            button._on_fill_tick()
            button.render(target)

        times: list[float] = []
        for _ in range(_PILL_ITERATIONS):
            start = time.perf_counter()
            button._on_fill_tick()
            button.render(target)
            times.append((time.perf_counter() - start) * 1000.0)

        parent.deleteLater()
        _app.processEvents()
    finally:
        motion.set_active_services(None)

    print("PillButton(water_fill=True), single instance")
    _report("1 button", times)


def bench_pill_button_concurrent() -> None:
    motion.set_active_services(_FakeServices())
    try:
        parent = QWidget()
        parent.resize(400, 900)
        parent.show()
        buttons = [_make_loading_pill(parent) for _ in range(_PILL_CONCURRENT_COUNT)]
        for i, button in enumerate(buttons):
            button.move(10, 10 + i * 46)
        target = QPixmap(buttons[0].size())

        for _ in range(5):
            for button in buttons:
                button._on_fill_tick()
                button.render(target)

        frame_times: list[float] = []
        for _ in range(_PILL_ITERATIONS):
            start = time.perf_counter()
            for button in buttons:
                button._on_fill_tick()
                button.render(target)
            frame_times.append((time.perf_counter() - start) * 1000.0)

        parent.deleteLater()
        _app.processEvents()
    finally:
        motion.set_active_services(None)

    print(f"PillButton(water_fill=True), {_PILL_CONCURRENT_COUNT} concurrent instances")
    _report(f"{_PILL_CONCURRENT_COUNT} buttons/frame", frame_times)
    per_button = [t / _PILL_CONCURRENT_COUNT for t in frame_times]
    _report("  -> per button", per_button)


# --- FadeStackedWidget --------------------------------------------------------

_TRANSITION_REPS = 20


def _run_one_crossfade(stack: FadeStackedWidget, target_index: int) -> float:
    start = time.perf_counter()
    stack.setCurrentIndex(target_index)
    anim = stack._anim
    if anim is not None:
        deadline = time.perf_counter() + 2.0  # safety net; real anim is 220ms
        while anim.state() == anim.State.Running and time.perf_counter() < deadline:
            _app.processEvents()
    return (time.perf_counter() - start) * 1000.0


def bench_fade_stacked_widget() -> None:
    services = _FakeServices()
    parent = QWidget()
    parent.resize(800, 600)
    stack = FadeStackedWidget(parent, services=services)
    for i in range(2):
        page = QWidget()
        page.setObjectName(f"page{i}")
        stack.addWidget(page)
    parent.show()

    times: list[float] = []
    for i in range(_TRANSITION_REPS):
        times.append(_run_one_crossfade(stack, i % 2))

    parent.deleteLater()
    _app.processEvents()

    print("FadeStackedWidget (one full 220ms crossfade, setCurrentIndex start-to-finish)")
    _report("1 crossfade", times)


# --- WaterSplashOverlay --------------------------------------------------------

_SPLASH_REPS = 20


def _run_one_splash(parent: QWidget) -> float:
    start = time.perf_counter()
    overlay = WaterSplashOverlay(parent, QPoint(40, 20))
    deadline = time.perf_counter() + 2.0  # safety net; real anim is 420ms
    while overlay is not None and time.perf_counter() < deadline:
        try:
            overlay.isVisible()
        except RuntimeError:
            break  # C++ object deleted -- self-deletion completed
        _app.processEvents()
    return (time.perf_counter() - start) * 1000.0


def bench_water_splash_overlay() -> None:
    parent = QWidget()
    parent.resize(180, 44)
    parent.show()

    times = [_run_one_splash(parent) for _ in range(_SPLASH_REPS)]

    parent.deleteLater()
    _app.processEvents()

    print("WaterSplashOverlay (one full 420ms click-splash lifecycle)")
    _report("1 splash", times)


# --- cProfile deep-dive -------------------------------------------------------


def profile_worst_case() -> None:
    width, height = _OCEAN_SIZES[-1]
    parent = QWidget()
    widget = OceanBackgroundWidget(_FakeServices(), parent)
    parent.resize(width, height)
    parent.show()
    widget.resize(width, height)
    widget.set_mouse_norm(0.35, -0.2)
    target = QPixmap(width, height)

    for _ in range(5):
        widget._on_tick()
        widget.render(target)

    profiler = cProfile.Profile()
    profiler.enable()
    for _ in range(_OCEAN_ITERATIONS):
        widget._on_tick()
        widget.render(target)
    profiler.disable()

    parent.deleteLater()
    _app.processEvents()

    print(f"cProfile: OceanBackgroundWidget at {width}x{height}, {_OCEAN_ITERATIONS} frames")
    print("Top 15 by cumulative time:")
    buffer = io.StringIO()
    stats = pstats.Stats(profiler, stream=buffer).sort_stats("cumulative")
    stats.print_stats(15)
    for line in buffer.getvalue().splitlines():
        print(f"  {line}")


def main() -> None:
    print("=" * 78)
    bench_ocean_background()
    print()
    bench_pill_button_single()
    print()
    bench_pill_button_concurrent()
    print()
    bench_fade_stacked_widget()
    print()
    bench_water_splash_overlay()
    print("=" * 78)
    print()
    profile_worst_case()


if __name__ == "__main__":
    main()
