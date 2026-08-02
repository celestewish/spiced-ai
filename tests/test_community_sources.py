import io
import urllib.error

import pytest

from spiced.core.community.discord_source import DiscordCommunitySource
from spiced.core.community.factory import available_sources, build_source
from spiced.core.community.mock_source import MockCommunitySource


def test_mock_source_is_always_available():
    source = MockCommunitySource()
    assert source.is_available() is True
    messages = source.fetch_recent(limit=3)
    assert len(messages) == 3
    assert "mock" in source.channel_label().lower()


def test_mock_source_respects_limit():
    source = MockCommunitySource()
    assert len(source.fetch_recent(limit=1)) == 1


def test_discord_unavailable_without_credentials():
    source = DiscordCommunitySource(token=None, channel_id=None)
    assert source.is_available() is False
    with pytest.raises(RuntimeError):
        source.fetch_recent()


def test_discord_available_with_both_credentials():
    source = DiscordCommunitySource(token="abc", channel_id="123")
    assert source.is_available() is True
    assert "123" in source.channel_label()


def test_discord_fetch_parses_and_reverses_order(monkeypatch):
    source = DiscordCommunitySource(token="abc", channel_id="123")
    payload = (
        b'[{"content": "newest", "author": {"username": "kel"}, "timestamp": "t2"},'
        b'{"content": "oldest", "author": {"username": "ari"}, "timestamp": "t1"}]'
    )

    class FakeResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None):
        return FakeResponse(payload)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    messages = source.fetch_recent(limit=10)
    assert [m.text for m in messages] == ["oldest", "newest"]
    assert messages[0].author == "ari"


def test_discord_friendly_error_on_401(monkeypatch):
    source = DiscordCommunitySource(token="bad", channel_id="123")

    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError("url", 401, "Unauthorized", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="rejected"):
        source.fetch_recent()


def test_discord_friendly_error_on_403(monkeypatch):
    source = DiscordCommunitySource(token="abc", channel_id="123")

    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError("url", 403, "Forbidden", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    with pytest.raises(RuntimeError, match="isn't allowed"):
        source.fetch_recent()


def test_factory_builds_known_sources():
    assert isinstance(build_source("mock"), MockCommunitySource)
    assert isinstance(build_source("discord"), DiscordCommunitySource)
    assert set(available_sources()) == {"mock", "discord"}


def test_factory_rejects_unknown_source():
    with pytest.raises(ValueError):
        build_source("carrier-pigeon")
