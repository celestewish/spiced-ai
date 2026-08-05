"""Tests for core.community.discord_poster: opt-in write capability.

Mirrors test_community_sources.py's pattern for the read-only
DiscordCommunitySource — urllib.request.urlopen is monkeypatched so no real
Discord call is ever made.
"""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from spiced.core.community.discord_poster import MAX_MESSAGE_CHARS, DiscordPoster


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_unavailable_without_credentials():
    poster = DiscordPoster(token=None, channel_id=None)
    assert poster.is_available() is False
    with pytest.raises(RuntimeError):
        poster.post_message("hello")


def test_available_with_both_credentials():
    poster = DiscordPoster(token="abc", channel_id="123")
    assert poster.is_available() is True
    assert "123" in poster.channel_label()


def test_prefers_explicit_announce_channel_over_env(monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "env-token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "read-channel")
    monkeypatch.setenv("DISCORD_ANNOUNCE_CHANNEL_ID", "announce-channel")
    poster = DiscordPoster()
    assert poster.channel_label() == "Discord channel announce-channel"


def test_falls_back_to_read_channel_when_no_announce_channel_set(monkeypatch):
    monkeypatch.delenv("DISCORD_ANNOUNCE_CHANNEL_ID", raising=False)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "env-token")
    monkeypatch.setenv("DISCORD_CHANNEL_ID", "read-channel")
    poster = DiscordPoster()
    assert poster.channel_label() == "Discord channel read-channel"


def test_post_message_sends_content_to_messages_endpoint(monkeypatch):
    poster = DiscordPoster(token="abc", channel_id="123")
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen["url"] = request.full_url
        seen["method"] = request.get_method()
        seen["body"] = json.loads(request.data.decode("utf-8"))
        seen["headers"] = request.headers
        return FakeResponse(b"{}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    poster.post_message("Today's changelog: fixed the thing.")

    assert seen["url"] == "https://discord.com/api/v10/channels/123/messages"
    assert seen["method"] == "POST"
    assert seen["body"] == {"content": "Today's changelog: fixed the thing."}
    assert seen["headers"]["Authorization"] == "Bot abc"


def test_post_message_rejects_empty_text():
    poster = DiscordPoster(token="abc", channel_id="123")
    with pytest.raises(ValueError):
        poster.post_message("   ")


def test_post_message_truncates_overlong_text(monkeypatch):
    poster = DiscordPoster(token="abc", channel_id="123")
    seen = {}

    def fake_urlopen(request, timeout=None):
        seen["body"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse(b"{}")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    poster.post_message("x" * (MAX_MESSAGE_CHARS + 500))

    assert len(seen["body"]["content"]) == MAX_MESSAGE_CHARS


def test_post_message_friendly_error_on_401(monkeypatch):
    poster = DiscordPoster(token="bad", channel_id="123")

    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="rejected"):
        poster.post_message("hello")


def test_post_message_friendly_error_on_403(monkeypatch):
    poster = DiscordPoster(token="abc", channel_id="123")

    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError("url", 403, "Forbidden", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="isn't allowed"):
        poster.post_message("hello")


def test_post_message_network_error(monkeypatch):
    poster = DiscordPoster(token="abc", channel_id="123")

    def fake_urlopen(request, timeout=None):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="Could not reach Discord"):
        poster.post_message("hello")
