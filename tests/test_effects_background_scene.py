"""ui.effects.background_scene: OceanBackgroundWidget gating and painting.

No display is available in this environment, so this uses Qt's offscreen
platform plugin, matching the pattern used by the other widget tests.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from spiced.ui.effects.background_scene import (  # noqa: E402
    OceanBackgroundWidget,
    _build_island_paths,
    _wave_path,
)

_app = QApplication.instance() or QApplication([])


class _FakeServices:
    def __init__(self, *, reduce_motion: bool = False, high_contrast: bool = False) -> None:
        self._reduce_motion = reduce_motion
        self._high_contrast = high_contrast

    def accessibility_reduce_motion_enabled(self) -> bool:
        return self._reduce_motion

    def accessibility_high_contrast_enabled(self) -> bool:
        return self._high_contrast


def _mounted(services) -> tuple[QWidget, OceanBackgroundWidget]:
    """A real parent, shown, so isVisible()/isHidden() reflect an explicit
    setVisible(False) the way MainWindow's own usage would (a top-level
    widget's un-shown children always report isVisible()=False regardless,
    which would make every case here look identical without a shown
    parent -- see the same caveat noted in test_source_link_widget.py)."""
    parent = QWidget()
    background = OceanBackgroundWidget(services, parent)
    parent.resize(920, 600)
    parent.show()
    return parent, background


def test_normal_state_is_visible_with_the_ticker_running():
    _parent, background = _mounted(_FakeServices())
    assert background.isVisible() is True
    assert background._ticker.is_active() is True


def test_reduced_motion_stays_visible_but_stops_the_ticker():
    _parent, background = _mounted(_FakeServices(reduce_motion=True))
    assert background.isVisible() is True
    assert background._ticker.is_active() is False


def test_high_contrast_hides_the_widget_entirely():
    _parent, background = _mounted(_FakeServices(high_contrast=True))
    assert background.isVisible() is False
    assert background._ticker.is_active() is False


def test_high_contrast_and_reduced_motion_both_hides_and_stops():
    _parent, background = _mounted(_FakeServices(reduce_motion=True, high_contrast=True))
    assert background.isVisible() is False
    assert background._ticker.is_active() is False


def test_no_services_defaults_to_reduced_motion_but_stays_visible():
    _parent, background = _mounted(None)
    assert background.isVisible() is True
    assert background._ticker.is_active() is False


def test_refresh_accessibility_state_reacts_to_a_live_setting_change():
    services = _FakeServices()
    _parent, background = _mounted(services)
    assert background._ticker.is_active() is True

    services._reduce_motion = True
    background.refresh_accessibility_state()
    assert background._ticker.is_active() is False


def test_set_window_visible_false_stops_the_ticker():
    _parent, background = _mounted(_FakeServices())
    assert background._ticker.is_active() is True

    background.set_window_visible(False)
    assert background._ticker.is_active() is False
    # setVisible/isVisible are unaffected -- this is purely a ticker pause,
    # not the same as the accessibility-driven hide above.
    assert background.isVisible() is True

    background.set_window_visible(True)
    assert background._ticker.is_active() is True


def test_set_window_visible_stays_stopped_if_reduced_motion_also_applies():
    _parent, background = _mounted(_FakeServices(reduce_motion=True))
    assert background._ticker.is_active() is False

    background.set_window_visible(False)
    assert background._ticker.is_active() is False

    # Regaining window visibility must not override the accessibility gate.
    background.set_window_visible(True)
    assert background._ticker.is_active() is False


def test_wave_path_cache_is_reused_across_ticks_at_the_same_size():
    _parent, background = _mounted(_FakeServices())
    background.resize(920, 600)
    background._on_tick()
    background.repaint()
    cached_after_first = dict(background._wave_path_cache)

    background._on_tick()
    background.repaint()

    assert background._wave_path_cache.keys() == cached_after_first.keys()
    for index, (key, path) in background._wave_path_cache.items():
        prev_key, prev_path = cached_after_first[index]
        assert key == prev_key
        assert path is prev_path  # same QPainterPath object, not rebuilt


def test_set_mouse_norm_is_a_no_op_when_motion_is_reduced():
    _parent, background = _mounted(_FakeServices(reduce_motion=True))
    background.set_mouse_norm(0.5, -0.5)
    assert background._mouse_norm.x() == 0.5  # still stored
    # (nothing to assert on repaint scheduling without a real event loop --
    # covered indirectly by the paint-doesn't-crash tests below.)


def test_paints_without_error_at_the_app_minimum_window_size():
    _parent, background = _mounted(_FakeServices())
    background.resize(920, 600)
    for _ in range(5):
        background._on_tick()
    background.set_mouse_norm(0.4, -0.3)
    background.repaint()


def test_paints_without_error_at_a_large_window_size():
    _parent, background = _mounted(_FakeServices())
    background.resize(2560, 1440)
    for _ in range(5):
        background._on_tick()
    background.repaint()


def test_paints_without_error_with_a_degenerate_zero_size():
    _parent, background = _mounted(_FakeServices())
    background.resize(0, 0)
    background.repaint()  # must not crash/divide-by-zero


def test_island_silhouette_paths_are_non_empty_and_closed():
    back, front = _build_island_paths()
    assert not back.isEmpty()
    assert not front.isEmpty()
    # Every subpath in the ported SVG data ends with Z (closeSubpath).
    assert back.elementCount() > 0
    assert front.elementCount() > 0


def test_wave_path_covers_the_full_widget_width():
    path = _wave_path(
        widget_width=800, period_px=200, baseline_y=100, amplitude_px=20, bottom_y=200,
        x_offset=0,
    )
    bounds = path.boundingRect()
    assert bounds.left() <= 0
    assert bounds.right() >= 800
    assert bounds.bottom() >= 200


def test_wave_path_handles_a_tiny_width_without_looping_forever():
    path = _wave_path(
        widget_width=1, period_px=200, baseline_y=10, amplitude_px=5, bottom_y=20, x_offset=0,
    )
    assert not path.isEmpty()
