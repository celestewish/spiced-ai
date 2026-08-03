"""Small local config for Small-Team Mode: which Supabase project and backend to talk to.

Read from the environment (or a local .env, loaded the same way OPENAI_API_KEY
is at app startup) rather than hardcoded. The Supabase anon key is a public,
rate-limited key that's safe to ship in client code, but is still kept out of
source so a solo, offline developer never carries any team-mode configuration.
The service role key is a backend-only secret and is never read here.
"""

from __future__ import annotations

import os

DEFAULT_BACKEND_URL = "http://127.0.0.1:8000"


def supabase_url() -> str:
    return os.environ.get("SUPABASE_URL", "").strip()


def supabase_anon_key() -> str:
    return os.environ.get("SUPABASE_ANON_KEY", "").strip()


def backend_base_url() -> str:
    return os.environ.get("SPICED_BACKEND_URL", DEFAULT_BACKEND_URL).strip()


def is_configured() -> bool:
    """True once enough is set for Team Mode to work at all."""
    return bool(supabase_url() and supabase_anon_key())
