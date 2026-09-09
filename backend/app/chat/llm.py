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
def chat_model(model: str, **kwargs):
    from langchain_anthropic import ChatAnthropic

    if not settings.anthropic_api_key:
        raise RuntimeError("LLM_BACKEND=claude but ANTHROPIC_API_KEY is not set")
    return ChatAnthropic(model=model, api_key=settings.anthropic_api_key, **kwargs)


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
