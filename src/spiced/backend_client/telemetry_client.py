"""Anonymous, opt-in feature-usage telemetry HTTP call.

Deliberately kept structurally separate from ``BackendClient`` (which always
attaches the signed-in user's Supabase JWT as a Bearer token for Small-Team
Mode calls). This module never reads or sends an auth token, a user id, or an
email — only ``anonymous_client_id`` (a random UUID minted once and stored
locally, see ``app.services.Services.record_telemetry_event``) and a bare
``event_name`` are ever sent. That keeps the "telemetry is anonymous even for
a signed-in developer" privacy boundary true by construction rather than by
convention: there's no ``self._token`` anywhere in this module to forget to
omit.
"""

from __future__ import annotations

import httpx

from spiced.backend_client import config

_TIMEOUT = 5.0


def post_event(anonymous_client_id: str, event_name: str, base_url: str | None = None) -> None:
    """Fire a single telemetry event. Raises on failure; callers swallow it.

    Kept as a raising function (rather than swallowing errors itself) so it
    stays simple and testable; ``Services.record_telemetry_event`` is the one
    place responsible for making this fire-and-forget from the caller's
    point of view.
    """
    url = f"{(base_url or config.backend_base_url()).rstrip('/')}/telemetry"
    with httpx.Client(timeout=_TIMEOUT) as client:
        client.post(
            url, json={"anonymous_client_id": anonymous_client_id, "event_name": event_name}
        )
