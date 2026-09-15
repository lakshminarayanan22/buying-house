"""Score the Ask box on questions with known answers.

    python -m scripts.eval_sql                         # whatever .env configures
    python -m scripts.eval_sql --sql-model hf.co/...   # try a SQL specialist for the SQL step
    python -m scripts.eval_sql --only 4,5              # a subset, by number

Runs each question through the real graph against the real database and checks the answer
text against evals/sql_questions.json. The checks are deliberately loose — a phrase has to
appear, wording is free — so a pass means the fact is right, not that the sentence matches.
Read the failures, not just the score: a check can be wrong too.
"""
import argparse
import json
import pathlib
import re
import sys
import time

from app.chat.graph import answer
from app.config import settings

QUESTIONS = pathlib.Path(__file__).resolve().parent.parent / "evals" / "sql_questions.json"


def normalise(text: str) -> str:
    return re.sub(r"[,$]", "", (text or "").lower())


def grade(answer_text: str, expect: list[list[str]], reject: list[str]) -> tuple[bool, str]:
    text = normalise(answer_text)
    for group in expect:
        if not any(normalise(alt) in text for alt in group):
            return False, f"missing {group}"
    for phrase in reject:
        if normalise(phrase) in text:
            return False, f"said {phrase!r}"
    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sql-model", help="override OLLAMA_SQL_MODEL for this run")
    parser.add_argument("--only", help="comma-separated question numbers, 1-based")
    args = parser.parse_args()

    if args.sql_model is not None:
        settings.ollama_sql_model = args.sql_model or None
    cases = json.loads(QUESTIONS.read_text())["questions"]
    if args.only:
        wanted = {int(n) for n in args.only.split(",")}
        cases = [c for i, c in enumerate(cases, 1) if i in wanted]

    print(f"model: {settings.llm_backend} {settings.ollama_model}"
          f" | sql: {settings.ollama_sql_model or '(same model)'}\n")
    passed, took = 0, []
    by_set: dict[str, list[int]] = {}
    for i, case in enumerate(cases, 1):
        start = time.time()
        try:
            state = answer(case["q"], user_id=None, user_role="MEMBER")
            text = state.get("answer") or ""
        except Exception as exc:                     # a crash is a fail, not an abort
            state, text = {}, f"ERROR {type(exc).__name__}: {exc}"
        took.append(time.time() - start)
        ok, why = grade(text, case["expect"], case.get("reject", []))
        passed += ok
        tally = by_set.setdefault(case.get("set", "all"), [0, 0])
        tally[0] += ok
        tally[1] += 1
        c = state.get("classification")
        print(f"{'PASS' if ok else 'FAIL'}  {i:>2}. {case['q']}  ({took[-1]:.0f}s, "
              f"{c.primary.value if c else '?'})")
        if not ok:
            print(f"        {why}\n        answer: {text[:220]}")
            if state.get("sql"):
                print(f"        sql:    {state['sql'][:220]}")
        if state.get("retrieved"):
            time.sleep(21)                           # Voyage allows 3 requests a minute here

    print(f"\nscore {passed}/{len(cases)}  ·  median {sorted(took)[len(took) // 2]:.0f}s per question")
    for name, (ok_count, total) in by_set.items():
        print(f"  {name:>5}: {ok_count}/{total}")
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    sys.exit(main())
