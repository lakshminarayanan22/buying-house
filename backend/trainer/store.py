"""The corrections file: one JSON object per line, in the repo, committed like code.

JSONL rather than a database so a commit shows exactly which query changed and how. These
corrections are the training data, and data you cannot read in a diff is data nobody audits.
"""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Iterator

BACKEND = pathlib.Path(__file__).resolve().parent.parent
QUESTIONS = BACKEND / "evals" / "sql_eval_questions.json"
CORRECTIONS = BACKEND / "evals" / "sql_corrections.jsonl"

# todo     nothing done yet
# ok       XiYan's draft was right as it stands
# fixed    the draft was close; it was edited
# rewritten the draft was wrong enough to start again
# skip     the question itself is bad, or unanswerable — never trained on
STATUSES = ("todo", "ok", "fixed", "rewritten", "skip")


def questions(include_create: bool = False) -> list[dict]:
    data = json.loads(QUESTIONS.read_text())["questions"]
    if include_create:
        return data
    return [q for q in data if q.get("kind") != "create"]


def load() -> dict[str, dict]:
    if not CORRECTIONS.exists():
        return {}
    saved: dict[str, dict] = {}
    for line in CORRECTIONS.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            saved[row["id"]] = row
    return saved


def save(row: dict) -> None:
    """Rewrite the file with this row replaced. At a hundred questions the simplest thing that
    cannot corrupt itself beats an append log that needs compacting."""
    rows = load()
    row["updated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rows[row["id"]] = row
    CORRECTIONS.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows.values(), key=lambda r: r["id"])
    CORRECTIONS.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in ordered))


def blank(question: dict) -> dict:
    return {
        "id": question["id"],
        "question": question["q"],
        "kind": question["kind"],
        "set": question["set"],
        "status": "todo",
        "draft_sql": "",
        "draft_model": "",
        "final_sql": "",
        "notes": "",
        "updated_at": "",
    }


def progress(rows: dict[str, dict], all_questions: list[dict]) -> dict:
    """How far through, and how often the model was right without help — the number that says
    whether fine-tuning is worth doing at all."""
    done = [rows[q["id"]] for q in all_questions
            if q["id"] in rows and rows[q["id"]]["status"] != "todo"]
    counted = [r for r in done if r["status"] != "skip"]
    right = [r for r in counted if r["status"] == "ok"]
    return {
        "done": len(done),
        "total": len(all_questions),
        "accepted": len(right),
        "counted": len(counted),
        "share": (len(right) / len(counted)) if counted else 0.0,
    }


def trainable(rows: dict[str, dict], scoring_ids: set[str]) -> Iterator[dict]:
    """Corrections that may be trained on: reviewed, not skipped, and never a scoring question."""
    for row in rows.values():
        if row["status"] in ("ok", "fixed", "rewritten") and row["id"] not in scoring_ids:
            if row.get("final_sql", "").strip():
                yield row
