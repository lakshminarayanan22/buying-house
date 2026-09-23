"""Spotting a request to create a record, and showing how to do it in the app instead.

Creating a record is the one write the chatbot deliberately does not do. A company has fifteen
fields and a deal leg has a role, a commission basis, a quantity and a price; a form asks for
each one, checks it, and shows what it captured. Dictating that to a chatbot is slower and
easier to get wrong, and a half-specified INSERT is a row nobody can trust afterwards.

So the answer is not a refusal — it is directions. Two layers catch the request, because one is
free and the other is certain:

  1. The phrase check here, which runs before any model call and costs nothing.
  2. guard.check(), which rejects an INSERT whatever the model generated — the backstop for a
     request phrased in a way no keyword list anticipated.

Because the reply is written here rather than by a model, it can name the real buttons, list the
fields the form asks for, and — when the question names a company or a deal we hold — say which
page to open. Updating and removing existing records is unaffected: those are one field on a row
somebody is already looking at, which a sentence does well.
"""
from __future__ import annotations

import re

from sqlalchemy import text
from sqlalchemy.orm import Session

# The verb has to be a creating one *and* aimed at a record. "Add up the commission" and "which
# deals were added in August" both contain "add"; neither asks us to create anything.
_CREATE = r"(?:add|create|insert|register|record|enter|set up|put in|log|onboard)"
_ARTICLE = r"(?:a|an|another|new|the new)"
_ASKS_TO_CREATE = re.compile(
    rf"\b{_CREATE}\b\s+(?:{_ARTICLE}\s+)?[\w '’-]*?\b"
    r"(compan(?:y|ies)|supplier|buyer|mill|factory|contact|person|deal|programme|program|"
    r"party|leg|milestone|follow[- ]?up|task|certification|certificate|process|capability|"
    r"product|client|document|file|note)\b",
    re.I,
)
_NOT_CREATING = re.compile(
    r"\b(?:add(?:ed|ing)?\s+up|was\s+added|were\s+added|been\s+added|who\s+added|"
    r"how\s+many|which|what|list|show|report|when\s+(?:was|were))\b",
    re.I,
)

_TARGETS = [
    (r"contact|person|phone number|email address", "contact"),
    (r"milestone|follow[- ]?up|task", "milestone"),
    (r"party|leg|to the chain|onto the deal|as the (?:buyer|supplier|processor)", "party"),
    (r"certification|certificate|process|capability|product|client", "capability"),
    (r"document|file|brochure|invoice|purchase order", "document"),
    (r"\bdeal\b|programme|program", "deal"),
    (r"compan|supplier|buyer|mill|factory|vendor", "company"),
]

# What each screen actually looks like, so the answer reads as directions rather than as a
# policy. Button names are quoted, not bolded: the dock renders an answer as plain text, so
# markdown asterisks would arrive on screen as asterisks.
STEPS = {
    "company": ("adding a company", [
        "Open “Companies” and press “Add a company”.",
        "Fill in the name, the country and the city, and tick whether they buy from us, sell to "
        "us, or both.",
        "Save, then add their processes, products and certifications on the company's page — "
        "those are what make them findable later.",
    ]),
    "contact": ("adding a contact", [
        "Open “Companies” and pick the company.",
        "In the “Contacts” card, fill in the name, role, phone and email.",
        "Press “Add contact”. The first contact you add becomes the primary one.",
    ]),
    "deal": ("starting a deal", [
        "Open “Deals” and press “New deal”.",
        "Give it a title, the product and the currency; the deal number is generated for you.",
        "Then add each company to the chain with its role, quantity, price and commission — the "
        "deal's value and what we earn are calculated from those legs.",
    ]),
    "party": ("adding a company to a deal", [
        "Open the deal and press “Add a company to the chain”.",
        "Pick the company and its role — buyer, supplier, processor, input supplier or other.",
        "Enter the quantity, price and commission basis. The commission is worked out from those.",
    ]),
    "milestone": ("adding a follow-up", [
        "Open the deal and find the “Follow-ups” section.",
        "Type what has to happen and the date it is planned for, under “Add a follow-up”.",
        "Its status starts as pending; change it there as the work moves.",
    ]),
    "capability": ("recording what a company can do", [
        "Open the company's page.",
        "Use the “Add” row under “What they do” to add a process, a product or a certification.",
        "Pick the value from the list rather than typing it, so search finds it later.",
    ]),
    "document": ("filing a document", [
        "Open the deal or the company it belongs to.",
        "Press “Add to this folder” and choose the file.",
        "Set what it is — brochure, purchase order, certificate — and it becomes searchable "
        "once the text is read.",
    ]),
}

_DEAL_NO = re.compile(r"\bDL-\d{4}-\d{4}\b", re.I)


def target_of(question: str) -> str:
    """Which kind of record the person wants to create. Company is the commonest default."""
    for pattern, name in _TARGETS:
        if re.search(pattern, question, re.I):
            return name
    return "company"


def asks_to_create(question: str) -> bool:
    if _NOT_CREATING.search(question):
        return False
    return bool(_ASKS_TO_CREATE.search(question))


def _mentioned(db: Session | None, question: str) -> str | None:
    """The company or deal the question names, if we hold it — so the directions can say which
    page to open rather than 'the company's page'."""
    if db is None:
        return None
    try:
        found = _DEAL_NO.search(question)
        if found:
            row = db.execute(text("SELECT deal_no, title FROM deal WHERE deal_no ILIKE :no"),
                             {"no": found.group(0)}).first()
            if row:
                return f"{row[0]} — {row[1]}"
        # Match the other way round: which stored name appears inside the sentence.
        row = db.execute(
            text("SELECT name FROM company WHERE :q ILIKE '%' || name || '%' "
                 "ORDER BY length(name) DESC LIMIT 1"),
            {"q": question},
        ).first()
        return row[0] if row else None
    except Exception:                      # noqa: BLE001 — directions are worth more than a trace
        return None


def handoff(question: str, db: Session | None = None) -> str:
    """Where and how to create this record. Written here, not by a model: the steps have to name
    the real buttons, and a model that invents a button is worse than no answer."""
    what, steps = STEPS[target_of(question)]
    named = _mentioned(db, question)

    lines = [f"That one is quicker in the app than through me — the form asks for every field "
             f"and checks it as you type. Here's {what}:"]
    lines.append("")
    lines += [f"{i}. {step}" for i, step in enumerate(steps, 1)]
    if named:
        lines.append("")
        lines.append(f"You mentioned {named} — start there.")
    lines.append("")
    lines.append("Once it exists I can take over: I can change or remove it from here, and "
                 "answer questions about it.")
    return "\n".join(lines)
