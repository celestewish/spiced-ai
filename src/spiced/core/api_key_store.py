"""Local storage for AI provider API keys entered through the Settings screen.

Connect-a-Project Setup Simplification spec, Finding 3 fix 1: a packaged
``.exe`` build has no shell and no ``.env`` file for a non-technical user to
edit, so ``OPENAI_API_KEY``/``GEMINI_API_KEY`` need an in-app fallback.
``ai.openai_provider``/``ai.gemini_provider`` each check the environment
variable first, falling back to ``get_api_key`` here only if it's unset --
see each provider's ``_api_key()``.

Deliberately a standalone plain-file store rather than a row in
``storage.settings.SettingsRepository`` (the app's general SQLite-backed
settings table): providers are constructible with zero arguments today and
don't otherwise depend on the app's database/``Services`` layer, and this
keeps it that way. Same trust tier as the existing local SQLite database
(``storage.database.default_db_path``) -- both live under the per-user
``~/.spiced`` folder -- and same promise as every other secret this codebase
handles: never sent anywhere but the provider itself.

Best-effort on read, like every other optional-metadata read in this
codebase (e.g. ``connectors.unity``'s version reads) -- a missing or
corrupt store just means "no key configured" rather than a crash.
"""

from __future__ import annotations

import json
from pathlib import Path


def _store_path() -> Path:
    base = Path.home() / ".spiced"
    base.mkdir(parents=True, exist_ok=True)
    return base / "api_keys.json"


def get_api_key(provider_key: str) -> str | None:
    """Return the stored key for ``provider_key`` (e.g. ``"openai"``), or
    ``None`` if none is saved or the store can't be read."""
    try:
        data = json.loads(_store_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get(provider_key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def set_api_key(provider_key: str, value: str) -> None:
    """Save the key for ``provider_key``, or clear it if ``value`` is blank."""
    path = _store_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
    except (OSError, json.JSONDecodeError):
        data = {}

    value = value.strip()
    if value:
        data[provider_key] = value
    else:
        data.pop(provider_key, None)
    path.write_text(json.dumps(data), encoding="utf-8")
