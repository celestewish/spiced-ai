"""RoadmapScreen: the changelog and suggestions sections must degrade to a
plain-language error message on any failure, never crash.

Regression coverage for a real gap: ``_refresh_changelog``/``_refresh_suggestions``
used to catch only ``(BackendAPIError, NotAuthenticatedError)``, unlike every
other network-calling path in the app (which wraps calls in a broad
``except Exception``). Since Roadmap's calls run synchronously in
``RoadmapScreen.__init__`` rather than on a worker thread, any other
exception -- a malformed response, a row missing an expected field -- used to
propagate uncaught out of construction, which (since MainWindow builds every
screen eagerly with no per-screen isolation) would take down the whole app.

No display is available in this environment, so this uses Qt's offscreen
platform plugin to construct the real screen headlessly, matching the
pattern used by the other screen tests (e.g. test_prototype_mode.py).
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from spiced.app.services import Services  # noqa: E402
from spiced.backend_client.api_client import BackendAPIError, ChangelogEntry  # noqa: E402
from spiced.ui.screens.roadmap import RoadmapScreen  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _services(tmp_path) -> Services:
    return Services(db_path=str(tmp_path / "spiced.db"))


def _entry() -> ChangelogEntry:
    return ChangelogEntry(
        id="c1",
        version_or_phase_label="Phase C",
        title="Open Roadmap shipped",
        body="You can now see the changelog and suggestions.",
        published_at="2026-08-01T00:00:00Z",
    )


def test_changelog_renders_entries_on_success(tmp_path):
    services = _services(tmp_path)
    services.roadmap.list_changelog = lambda: [_entry()]
    services.roadmap.list_suggestions = lambda: []

    screen = RoadmapScreen(services)

    assert screen._changelog_error.text() == ""
    assert screen._changelog_layout.count() == 1


def test_changelog_shows_a_friendly_message_on_backend_error(tmp_path):
    services = _services(tmp_path)

    def _raise():
        raise BackendAPIError("Could not reach the Spiced backend: connection refused")

    services.roadmap.list_changelog = _raise
    services.roadmap.list_suggestions = lambda: []

    screen = RoadmapScreen(services)

    assert "Couldn't reach the roadmap backend" in screen._changelog_error.text()
    assert screen._changelog_layout.count() == 0


def test_changelog_survives_an_unexpected_exception_instead_of_crashing(tmp_path):
    # The regression case: a bug in the backend response shape (e.g. a row
    # missing an expected field raises KeyError deep in _changelog_entry)
    # must not propagate out of __init__ and take the whole app down with it.
    services = _services(tmp_path)

    def _raise():
        raise KeyError("published_at")

    services.roadmap.list_changelog = _raise
    services.roadmap.list_suggestions = lambda: []

    screen = RoadmapScreen(services)  # must not raise

    assert "Couldn't load the changelog" in screen._changelog_error.text()
    assert screen._changelog_layout.count() == 0


def test_suggestions_renders_on_success(tmp_path):
    from spiced.backend_client.api_client import RoadmapSuggestion

    services = _services(tmp_path)
    services.roadmap.list_changelog = lambda: []
    services.roadmap.list_suggestions = lambda: [
        RoadmapSuggestion(
            id="s1",
            author_user_id="u1",
            title="Add dark mode",
            body="Please",
            created_at="2026-08-01T00:00:00Z",
            vote_count=0,
            voted_by_me=False,
        )
    ]

    screen = RoadmapScreen(services)

    assert screen._suggestions_error.text() == ""
    assert screen._suggestions_layout.count() == 1


def test_suggestions_survives_an_unexpected_exception_instead_of_crashing(tmp_path):
    services = _services(tmp_path)
    services.roadmap.list_changelog = lambda: []

    def _raise():
        raise ValueError("unexpected response shape")

    services.roadmap.list_suggestions = _raise

    screen = RoadmapScreen(services)  # must not raise

    assert "Couldn't load suggestions" in screen._suggestions_error.text()
    assert screen._suggestions_layout.count() == 0
