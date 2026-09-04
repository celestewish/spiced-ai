"""Services.backend_reachable(): a single cached reachability check shared by
Roadmap and Settings' notification panels, so a down backend is discovered
(and reported) once per app run instead of by each caller independently.
"""

from __future__ import annotations

from spiced.app.services import Services


def _services(tmp_path) -> Services:
    return Services(db_path=str(tmp_path / "spiced.db"))


def test_backend_reachable_is_cached_after_first_check(tmp_path):
    services = _services(tmp_path)
    calls = []
    services.roadmap.ping = lambda: calls.append(1) or False

    assert services.backend_reachable() is False
    assert services.backend_reachable() is False
    assert services.backend_reachable() is False

    assert calls == [1]  # only pinged once, not once per call


def test_refresh_backend_reachable_forces_a_new_check(tmp_path):
    services = _services(tmp_path)
    results = iter([False, True])
    services.roadmap.ping = lambda: next(results)

    assert services.backend_reachable() is False
    assert services.backend_reachable() is False  # still cached False
    assert services.refresh_backend_reachable() is True
    assert services.backend_reachable() is True  # now cached True
