"""telemetry_client.post_event: no auth header, anonymous body only."""

from __future__ import annotations

import httpx
import pytest

from spiced.backend_client import telemetry_client


def test_post_event_sends_no_authorization_header(monkeypatch):
    seen = {}

    class _FakeClient:
        def __init__(self, timeout):
            self._timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, json):
            seen["url"] = url
            seen["json"] = json
            return httpx.Response(201, json={})

    monkeypatch.setattr(telemetry_client.httpx, "Client", _FakeClient)
    telemetry_client.post_event("client-abc", "debugging.crash_diagnosis_run", base_url="http://testserver")

    assert seen["url"] == "http://testserver/telemetry"
    assert seen["json"] == {
        "anonymous_client_id": "client-abc",
        "event_name": "debugging.crash_diagnosis_run",
    }
    # Structurally cannot carry a token: no "headers" kwarg is ever passed.


def test_post_event_raises_on_network_error(monkeypatch):
    class _FailingClient:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def post(self, url, json):
            raise httpx.ConnectError("refused")

    monkeypatch.setattr(telemetry_client.httpx, "Client", _FailingClient)
    with pytest.raises(httpx.ConnectError):
        telemetry_client.post_event("client-abc", "some.event")
