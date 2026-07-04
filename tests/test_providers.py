
from spiced.ai import MockProvider, build_provider
from spiced.ai.gemini_provider import GeminiProvider


def test_mock_provider_always_available():
    provider = MockProvider()
    assert provider.is_available()
    response = provider.generate("Why is my player falling through the floor?")
    assert response.provider == "mock"
    assert response.text


def test_factory_builds_known_providers():
    assert isinstance(build_provider("mock"), MockProvider)
    assert isinstance(build_provider("gemini"), GeminiProvider)


def test_gemini_unavailable_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    assert GeminiProvider().is_available() is False


def test_gemini_generate_raises_without_key(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    provider = GeminiProvider()
    try:
        provider.generate("hello")
    except RuntimeError as exc:
        assert "GEMINI_API_KEY" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected RuntimeError when key is missing")
