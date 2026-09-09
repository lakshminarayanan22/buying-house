"""The graph: classify, branch, optionally run a second branch, compose.

LangGraph rather than a hand-rolled conditional because the plan calls for it and because the
state, streaming and checkpointing come free when this grows.
"""
from __future__ import annotations

import logging
import uuid

from langgraph.graph import END, StateGraph

from app.chat import branches
from app.chat.classifier import classify, route
from app.chat.llm import is_stub
from app.chat.state import Category, ChatState
from app.config import settings

logger = logging.getLogger(__name__)

_NODES = {
    Category.DATABASE.value: branches.database,
    Category.TECHNICAL.value: branches.technical,
    Category.CREATIVE.value: branches.creative,
}


def _clarify(state: ChatState) -> ChatState:
    state["answer"] = state["needs_clarification"]
    return state


def _secondary(state: ChatState) -> ChatState:
    """Run the second category too, and stitch the two answers together.

    Without this a two-part question gets half an answer with no indication that the other
    half was dropped.
    """
    classification = state.get("classification")
    if not classification or not classification.secondary:
        return state
    if classification.secondary == classification.primary:
        return state

    node = _NODES.get(classification.secondary.value)
    if node is None:
        return state

    primary_answer = state.get("answer") or ""
    second = node(dict(state))
    state.setdefault("trace", []).append(f"also ran {classification.secondary}")

    extra = second.get("answer") or ""
    if extra and extra not in primary_answer:
        state["answer"] = f"{primary_answer}\n\n{extra}".strip()
    state["citations"] = list(dict.fromkeys(
        (state.get("citations") or []) + (second.get("citations") or [])))
    return state


def build_graph():
    graph = StateGraph(ChatState)
    graph.add_node("classify", classify)
    graph.add_node("clarify", _clarify)
    for name, fn in _NODES.items():
        graph.add_node(name, fn)
    graph.add_node("secondary", _secondary)

    graph.set_entry_point("classify")
    graph.add_conditional_edges("classify", route, {
        "clarify": "clarify",
        Category.DATABASE.value: Category.DATABASE.value,
        Category.TECHNICAL.value: Category.TECHNICAL.value,
        Category.CREATIVE.value: Category.CREATIVE.value,
    })
    for name in _NODES:
        graph.add_edge(name, "secondary")
    graph.add_edge("secondary", END)
    graph.add_edge("clarify", END)
    return graph.compile()


_compiled = None


def answer(question: str, *, user_id: str | None = None,
           user_role: str = "MEMBER") -> ChatState:
    """Run one question through the graph."""
    global _compiled
    if _compiled is None:
        _compiled = build_graph()

    if is_stub():
        logger.warning("LLM_BACKEND=stub — keyword routing and templated answers, not a chatbot")

    return _compiled.invoke({
        "question": question, "user_id": user_id or "", "user_role": user_role,
        "retrieved": [], "citations": [], "trace": [],
    })
