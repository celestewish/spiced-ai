"""Services.tutorial_completed()/set_tutorial_completed() -- the first-launch
tutorial's persisted "already seen it" flag (In-App Tutorial spec). Same
thin key/value shape as the existing accessibility settings; this is that
shape's own regression coverage.
"""

from __future__ import annotations

from spiced.app.services import Services


def _services(tmp_path) -> Services:
    return Services(db_path=str(tmp_path / "spiced.db"))


def test_tutorial_completed_defaults_to_false(tmp_path):
    assert _services(tmp_path).tutorial_completed() is False


def test_set_tutorial_completed_true_round_trips(tmp_path):
    services = _services(tmp_path)
    services.set_tutorial_completed(True)
    assert services.tutorial_completed() is True


def test_set_tutorial_completed_false_round_trips(tmp_path):
    services = _services(tmp_path)
    services.set_tutorial_completed(True)
    services.set_tutorial_completed(False)
    assert services.tutorial_completed() is False


def test_tutorial_completed_persists_across_service_instances(tmp_path):
    db_path = str(tmp_path / "spiced.db")
    Services(db_path=db_path).set_tutorial_completed(True)
    assert Services(db_path=db_path).tutorial_completed() is True
