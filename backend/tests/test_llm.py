"""Which model each backend builds. Construction only — nothing here talks to a server."""
import pytest

from app.chat import llm
from app.config import settings


def test_ollama_builds_the_local_qwen_with_the_settings_that_matter(monkeypatch):
    monkeypatch.setattr(settings, "llm_backend", "ollama")
    monkeypatch.setattr(settings, "ollama_model", "qwen3:8b")

    model = llm.chat_model("claude-sonnet-5", max_tokens=1200)

    assert type(model).__name__ == "ChatOllama"
    assert model.model == "qwen3:8b"          # the Claude name is ignored on this backend
    assert model.num_predict == 1200          # the caller's budget still applies
    assert model.reasoning is False           # no thinking block inside generated SQL
    assert model.num_ctx >= 8192              # the schema prompt must not be truncated


def test_classifier_and_branches_share_one_local_model(monkeypatch):
    monkeypatch.setattr(settings, "llm_backend", "ollama")
    a = llm.chat_model(settings.classifier_model, max_tokens=500)
    b = llm.chat_model(settings.branch_model, max_tokens=2000)
    assert a.model == b.model


def test_claude_still_needs_its_key(monkeypatch):
    monkeypatch.setattr(settings, "llm_backend", "claude")
    monkeypatch.setattr(settings, "anthropic_api_key", None)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        llm.chat_model(settings.branch_model)


def test_an_unknown_backend_is_named_in_the_error(monkeypatch):
    monkeypatch.setattr(settings, "llm_backend", "qwen")
    with pytest.raises(RuntimeError, match="stub, ollama or claude"):
        llm.chat_model(settings.branch_model)
