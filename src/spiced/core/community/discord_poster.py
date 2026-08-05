"""Real, write-capable Discord posting (Phase G, section 7, Phase 2 tier).

Deliberately a separate class from the existing read-only
``DiscordCommunitySource`` (``core/community/discord_source.py``): reading
one public channel's history and posting a message are meaningfully
different trust boundaries (opt-in-read vs. opt-in-*write*), so they get
distinct opt-in settings even though both reuse the same
``DISCORD_BOT_TOKEN`` env var already established for the read side.

Posting always requires the caller to have already shown the developer the
exact text and gotten an explicit click before calling ``post_message`` —
this module has no opinion on that UI flow; see the confirm-before-send
dialog on the Debugging Buddy screen's "Post to Discord" action. Off by
default: the developer must set ``DISCORD_BOT_TOKEN`` plus a channel id and
explicitly turn on "Discord integration" in Settings (separate from the
existing Community Pulse toggle).

Channel id: the spec describes posting to "a connected Discord server"
generically. Rather than invent a second, distinct "announcements channel"
concept, this reuses ``DISCORD_CHANNEL_ID`` (the same channel Community
Pulse reads from) by default — a deliberate, honestly-scoped simplification.
``DISCORD_ANNOUNCE_CHANNEL_ID`` is supported as an optional override for a
developer who wants posts to land somewhere different from where Spiced
reads community chatter.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

API_BASE = "https://discord.com/api/v10"
USER_AGENT = "Spiced (https://github.com/celestewish/spiced-ai, 1.0)"
REQUEST_TIMEOUT_S = 10
MAX_MESSAGE_CHARS = 2000  # Discord's own hard per-message limit


class DiscordPoster:
    name = "discord"

    def __init__(self, token: str | None = None, channel_id: str | None = None) -> None:
        self._token = token or os.environ.get("DISCORD_BOT_TOKEN")
        self._channel_id = (
            channel_id
            or os.environ.get("DISCORD_ANNOUNCE_CHANNEL_ID")
            or os.environ.get("DISCORD_CHANNEL_ID")
        )

    def is_available(self) -> bool:
        return bool(self._token and self._channel_id)

    def channel_label(self) -> str:
        if not self._channel_id:
            return "Discord (not configured)"
        return f"Discord channel {self._channel_id}"

    def post_message(self, text: str) -> None:
        """Post ``text`` verbatim to the configured channel.

        Callers must have already shown the developer this exact text and
        gotten an explicit confirmation — this function performs no
        confirmation of its own. Raises ``RuntimeError``/``ValueError`` with
        a friendly message on any failure.
        """
        if not self.is_available():
            raise RuntimeError(
                "DISCORD_BOT_TOKEN and a channel id (DISCORD_CHANNEL_ID or "
                "DISCORD_ANNOUNCE_CHANNEL_ID) must both be set to post to Discord. Add them to "
                "your environment or a local .env file (see .env.example)."
            )
        body = text.strip()
        if not body:
            raise ValueError("Nothing to post — the message is empty.")
        if len(body) > MAX_MESSAGE_CHARS:
            body = body[: MAX_MESSAGE_CHARS - 1] + "…"

        url = f"{API_BASE}/channels/{self._channel_id}/messages"
        payload = json.dumps({"content": body}).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bot {self._token}",
                "User-Agent": USER_AGENT,
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT_S) as response:
                response.read()
        except urllib.error.HTTPError as exc:
            raise self._friendly_error(exc) from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Could not reach Discord: {exc.reason}") from exc

    def _friendly_error(self, exc: urllib.error.HTTPError) -> RuntimeError:
        if exc.code == 401:
            return RuntimeError("Discord rejected DISCORD_BOT_TOKEN — double-check it for typos.")
        if exc.code == 403:
            return RuntimeError(
                "Discord says this bot isn't allowed to post in that channel. Confirm the bot "
                "has been added to the server with permission to send messages there."
            )
        if exc.code == 404:
            return RuntimeError(
                "The configured Discord channel id doesn't match a channel the bot can see."
            )
        return RuntimeError(f"Discord request failed: HTTP {exc.code}")

    def display_name(self) -> str:
        return "Discord"
