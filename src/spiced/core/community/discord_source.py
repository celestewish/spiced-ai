"""Real, read-only Discord community source.

Reads recent messages from one public channel via Discord's REST API using a
bot token — the same secrets policy as the AI providers (env var only, never
hardcoded, never logged). It only ever performs a GET on one channel's message
history: no posting, no reacting, no reading DMs, and no listing other
channels or servers. Off by default; the developer must set both
DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID and opt in from Settings.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from spiced.core.community.base import CommunityMessage, CommunitySource

API_BASE = "https://discord.com/api/v10"
USER_AGENT = "Spiced (https://github.com/celestewish/spiced-ai, 1.0)"
REQUEST_TIMEOUT_S = 10


class DiscordCommunitySource(CommunitySource):
    name = "discord"

    def __init__(self, token: str | None = None, channel_id: str | None = None) -> None:
        self._token = token or os.environ.get("DISCORD_BOT_TOKEN")
        self._channel_id = channel_id or os.environ.get("DISCORD_CHANNEL_ID")

    def is_available(self) -> bool:
        return bool(self._token and self._channel_id)

    def channel_label(self) -> str:
        if not self._channel_id:
            return "Discord (not configured)"
        return f"Discord channel {self._channel_id}"

    def fetch_recent(self, limit: int = 30) -> list[CommunityMessage]:
        if not self.is_available():
            raise RuntimeError(
                "DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID must both be set to read from "
                "Discord. Add them to your environment or a local .env file (see "
                ".env.example), or switch Community Pulse to the mock source."
            )
        capped_limit = max(1, min(int(limit), 100))
        url = f"{API_BASE}/channels/{self._channel_id}/messages?limit={capped_limit}"
        request = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bot {self._token}",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise self._friendly_error(exc) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach Discord: {exc.reason}") from exc

        messages = [
            CommunityMessage(
                author=(item.get("author") or {}).get("username", "unknown"),
                text=item.get("content", ""),
                timestamp=item.get("timestamp"),
            )
            for item in data
            if isinstance(item, dict) and item.get("content")
        ]
        # Discord returns newest-first; read oldest-to-newest like a transcript.
        return list(reversed(messages))

    def _friendly_error(self, exc: urllib.error.HTTPError) -> RuntimeError:
        if exc.code == 401:
            return RuntimeError("Discord rejected DISCORD_BOT_TOKEN — double-check it for typos.")
        if exc.code == 403:
            return RuntimeError(
                "Discord says this bot isn't allowed to read that channel. Confirm the bot has "
                "been added to the server with permission to view and read message history."
            )
        if exc.code == 404:
            return RuntimeError("DISCORD_CHANNEL_ID doesn't match a channel the bot can see.")
        return RuntimeError(f"Discord request failed: HTTP {exc.code}")

    def display_name(self) -> str:
        return "Discord"
