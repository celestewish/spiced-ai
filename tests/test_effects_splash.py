"""ui.effects.splash: WaterSplashOverlay lifecycle and attach_splash gating.

No display is available in this environment, so this uses Qt's offscreen
platform plugin and PySide6's bundled QtTest module (no new dependency --
pytest-qt isn't installed in this project) to simulate real mouse clicks,
matching the pattern used by the other widget tests (e.g.
test_source_link_widget.py).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import shiboken6  # noqa: E402
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton, QWidget  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.ui.effects import motion  # noqa: E402
from spiced.ui.effects.splash import WaterSplashOverlay, attach_splash  # noqa: E402
from spiced.ui.widgets.pill_button import PillButton  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _FakeServices:
    def __init__(self, *, reduce_motion: bool) -> None:
        self._reduce_motion = reduce_motion

    def accessibility_reduce_motion_enabled(self) -> bool:
        return self._reduce_motion


def test_overlay_covers_the_parent_and_never_intercepts_clicks():
    parent = QWidget()
    parent.resize(80, 32)
    overlay = WaterSplashOverlay(parent, QPoint(10, 10))
    try:
        assert overlay.geometry() == parent.rect()
        assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    finally:
        overlay.deleteLater()
        QApplication.processEvents()


def test_overlay_deletes_itself_once_its_animation_finishes():
    parent = QWidget()
    parent.resize(80, 32)
    overlay = WaterSplashOverlay(parent, QPoint(10, 10))

    overlay._anim.finished.emit()
    QApplication.processEvents()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QApplication.processEvents()

    assert shiboken6.isValid(overlay) is False


def test_attach_splash_spawns_an_overlay_when_motion_is_not_reduced():
    button = QPushButton()
    button.resize(60, 30)
    attach_splash(button, services=_FakeServices(reduce_motion=False))

    QTest.mouseClick(button, Qt.MouseButton.LeftButton)

    assert len(button.findChildren(WaterSplashOverlay)) == 1


def test_attach_splash_spawns_nothing_when_motion_is_reduced():
    button = QPushButton()
    button.resize(60, 30)
    attach_splash(button, services=_FakeServices(reduce_motion=True))

    QTest.mouseClick(button, Qt.MouseButton.LeftButton)

    assert button.findChildren(WaterSplashOverlay) == []


def test_attach_splash_never_blocks_the_real_click():
    button = QPushButton()
    button.resize(60, 30)
    attach_splash(button, services=_FakeServices(reduce_motion=False))

    clicked = []
    button.clicked.connect(lambda: clicked.append(True))
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)

    assert clicked == [True]


def test_attach_splash_falls_back_to_the_active_services_registry(monkeypatch):
    button = QPushButton()
    button.resize(60, 30)
    attach_splash(button)  # no services passed at attach time

    monkeypatch.setattr(motion, "_active_services", _FakeServices(reduce_motion=False))
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)

    assert len(button.findChildren(WaterSplashOverlay)) == 1


def test_attach_splash_registry_fallback_defaults_to_reduced(monkeypatch):
    button = QPushButton()
    button.resize(60, 30)
    attach_splash(button)

    monkeypatch.setattr(motion, "_active_services", None)
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)

    assert button.findChildren(WaterSplashOverlay) == []


def test_pill_button_gets_a_splash_automatically(tmp_path):
    # PillButton wires attach_splash(self) unconditionally in __init__ --
    # this covers every button built from it across the whole app,
    # including the notification bell (ui.notification_center.
    # NotificationBell builds its button from PillButton directly).
    services = Services(db_path=str(tmp_path / "spiced.db"))
    try:
        services.set_accessibility_reduce_motion_enabled(False)
        motion.set_active_services(services)

        button = PillButton("Click me")
        button.resize(80, 32)
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)

        assert len(button.findChildren(WaterSplashOverlay)) == 1
    finally:
        motion.set_active_services(None)
        services.close()


def test_pill_button_respects_reduce_motion(tmp_path):
    services = Services(db_path=str(tmp_path / "spiced.db"))
    try:
        services.set_accessibility_reduce_motion_enabled(True)
        motion.set_active_services(services)

        button = PillButton("Click me")
        button.resize(80, 32)
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)

        assert button.findChildren(WaterSplashOverlay) == []
    finally:
        motion.set_active_services(None)
        services.close()
