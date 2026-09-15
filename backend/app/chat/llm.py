"""Model access, with a stub so the graph can be built and tested without a key.

Same pattern as the embedding layer: the shape of the system should be provable before an API
key or a spend exists. The stub is honest about what it is — it does keyword routing and echoes
retrieved context — so nobody mistakes a passing test for a working chatbot.
"""
from __future__ import annotations

import logging
import re

from app.chat.state import Category, QueryClassification
from app.config import settings

logger = logging.getLogger(__name__)


def backend() -> str:
    return settings.llm_backend


def is_stub() -> bool:
    return settings.llm_backend == "stub"


# --------------------------------------------------------------------------- real
def chat_model(model: str, *, max_tokens: int = 1024):
    """The model for one step of the graph.

    Callers name the Claude model they would want (a fast one to classify, a stronger one to
    answer) and a token budget. On the Ollama backend both collapse to the one local model —
    every call site stays the same, which is what makes switching back to Claude one line in
    .env rather than a change to the graph.
    """
    backend = settings.llm_backend.lower()

    if backend == "claude":
        from langchain_anthropic import ChatAnthropic

        if not settings.anthropic_api_key:
            raise RuntimeError("LLM_BACKEND=claude but ANTHROPIC_API_KEY is not set")
        return ChatAnthropic(model=model, api_key=settings.anthropic_api_key,
                             max_tokens=max_tokens)

    if backend == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.ollama_model,
            base_url=settings.ollama_base_url,
            num_ctx=settings.ollama_num_ctx,
            num_predict=max_tokens,
            # Qwen3 reasons out loud before answering unless told not to. On a laptop that is
            # slow, and in the database branch the reasoning would land inside the "SQL" the
            # guard is handed. Off.
            reasoning=False,
            # Low but not zero: SQL wants to be deterministic, prose shouldn't be robotic.
            temperature=0.2,
            # Keep the weights loaded between questions; reloading 5 GB costs seconds each time.
            keep_alive="30m",
        )

    raise RuntimeError(f"LLM_BACKEND must be stub, ollama or claude — not {backend!r}")


def sql_model(*, max_tokens: int = 1200):
    """The model that writes SQL — a specialist when one is configured, else the branch model.

    Only on Ollama for now: a local SQL model (XiYan) sits next to the general one. The
    specialist gets no `reasoning` switch because it has no thinking mode to turn off, and a
    lower temperature because a query has one right answer.
    """
    if settings.llm_backend.lower() == "ollama" and settings.ollama_sql_model:
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.ollama_sql_model,
            base_url=settings.ollama_base_url,
            num_ctx=settings.ollama_num_ctx,
            num_predict=max_tokens,
            temperature=0.1,
            keep_alive="30m",
        )
    return chat_model(settings.branch_model, max_tokens=max_tokens)


def uses_xiyan() -> bool:
    """XiYan was trained on its own prompt layout; branches.py uses it when this is true."""
    return (settings.llm_backend.lower() == "ollama"
            and "xiyan" in (settings.ollama_sql_model or "").lower())


# --------------------------------------------------------------------------- stub
# Deliberately crude. Its job is to make the graph runnable, not to be a classifier — the
# moment it looks clever, someone will trust it.
_DATABASE_HINTS = re.compile(
    r"\b(deal|deals|commission|owed|owe|invoice[sd]?|ship|shipping|shipment|milestone|"
    r"outstanding|overdue|value|status|quiet|company|companies|supplier|buyer|contact|"
    r"moq|minimum order|capacity|certification|certified|process|how many|how much|list|"
    r"which|who)\b", re.I)
_TECHNICAL_HINTS = re.compile(
    r"\b(spec|specification|temperature|celsius|method|procedure|apply|application|"
    r"finish|dyeing|gsm|micronaire|staple|instruction|manual|brochure|document|"
    r"machinery|machine|spindle|stenter|how does|what does)\b", re.I)
_CREATIVE_HINTS = re.compile(
    r"\b(draft|write|compose|suggest|propose|recommend|plan|idea|pitch|summar|"
    r"introduce|email|message)\b", re.I)


def stub_classify(question: str) -> QueryClassification:
    scores = {
        Category.DATABASE: len(_DATABASE_HINTS.findall(question)),
        Category.TECHNICAL: len(_TECHNICAL_HINTS.findall(question)),
        Category.CREATIVE: len(_CREATIVE_HINTS.findall(question)) * 2,
    }
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top, top_score = ranked[0]
    second, second_score = ranked[1]

    if top_score == 0:
        return QueryClassification(
            primary=Category.TECHNICAL, confidence=0.3,
            reasoning="stub: no keywords matched, defaulting to document search",
        )
    total = sum(scores.values()) or 1
    return QueryClassification(
        primary=top,
        secondary=second if second_score and second_score >= top_score * 0.6 else None,
        confidence=min(0.95, 0.5 + top_score / (total + 1)),
        reasoning=f"stub: keyword counts {dict((k.value, v) for k, v in scores.items())}",
    )
