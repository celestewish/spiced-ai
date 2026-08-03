"""Opt-In Only Telemetry: settings round-trip and the anonymous, fire-and-
forget behavior of record_telemetry_event().
"""

from __future__ import annotations

from spiced.app.services import Services


def _services() -> Services:
    return Services(":memory:")


def test_telemetry_disabled_by_default():
    services = _services()
    assert services.telemetry_opt_in_enabled() is False


def test_telemetry_toggle_round_trips():
    services = _services()
    services.set_telemetry_opt_in_enabled(True)
    assert services.telemetry_opt_in_enabled() is True
    services.set_telemetry_opt_in_enabled(False)
    assert services.telemetry_opt_in_enabled() is False


def test_record_event_is_a_no_op_when_disabled(monkeypatch):
    services = _services()
    calls = []
    monkeypatch.setattr(
        "spiced.app.services.telemetry_client.post_event",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )
    services.record_telemetry_event("debugging.crash_diagnosis_run")
    assert calls == []


def test_record_event_posts_anonymous_client_id_and_event_name_when_enabled(monkeypatch):
    services = _services()
    services.set_telemetry_opt_in_enabled(True)
    calls = []
    monkeypatch.setattr(
        "spiced.app.services.telemetry_client.post_event",
        lambda client_id, event_name: calls.append((client_id, event_name)),
    )
    services.record_telemetry_event("testing.test_review_run")
    assert len(calls) == 1
    client_id, event_name = calls[0]
    assert event_name == "testing.test_review_run"
    assert client_id  # a non-empty anonymous id
    assert client_id != "" and "@" not in client_id  # never an email


def test_anonymous_client_id_is_stable_across_calls():
    services = _services()
    first = services._telemetry_client_id()
    second = services._telemetry_client_id()
    assert first == second


def test_record_event_never_raises_when_the_network_call_fails(monkeypatch):
    services = _services()
    services.set_telemetry_opt_in_enabled(True)

    def _boom(*args, **kwargs):
        raise RuntimeError("network is down")

    monkeypatch.setattr("spiced.app.services.telemetry_client.post_event", _boom)
    services.record_telemetry_event("feedback.analysis_run")  # must not raise
