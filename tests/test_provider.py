import sys
from types import SimpleNamespace

import pytest

from aifn.provider import OpenAIProvider, PlaceholderProvider, get_provider


def test_get_provider_returns_placeholder_by_default(monkeypatch):
    monkeypatch.delenv("AIFN_PROVIDER", raising=False)

    provider = get_provider()

    assert isinstance(provider, PlaceholderProvider)


def test_get_provider_builds_openai_provider(monkeypatch):
    class FakeOpenAI:
        def __init__(self):
            self.responses = SimpleNamespace(create=lambda **_: None)

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))

    provider = get_provider(name="openai", model="test-model")

    assert isinstance(provider, OpenAIProvider)
    assert provider.main_model == "test-model"


def test_get_provider_reads_fast_and_main_model_env(monkeypatch):
    class FakeOpenAI:
        def __init__(self):
            self.responses = SimpleNamespace(create=lambda **_: None)

    monkeypatch.setitem(sys.modules, "openai", SimpleNamespace(OpenAI=FakeOpenAI))
    monkeypatch.setenv("AIFN_MAIN_MODEL", "gpt-main")
    monkeypatch.setenv("AIFN_FAST_MODEL", "gpt-fast")

    provider = get_provider(name="openai")

    assert isinstance(provider, OpenAIProvider)
    assert provider.main_model == "gpt-main"
    assert provider.fast_model == "gpt-fast"


def test_get_provider_rejects_unknown_provider():
    with pytest.raises(ValueError, match="Unknown provider"):
        get_provider(name="anthropic")


def test_placeholder_provider_rejects_editing_existing_functions():
    provider = PlaceholderProvider()

    with pytest.raises(
        RuntimeError, match="Editing existing functions requires an AI provider"
    ):
        provider.edit_function(
            name="slugify",
            args=[],
            current_code="def slugify(*args):\n    return ''\n",
            current_tests="",
        )
