"""Score the router on questions with known categories.

    python -m scripts.eval_classify                    # whatever .env configures
    python -m scripts.eval_classify --set new          # the honest half only
    python -m scripts.eval_classify --model qwen3:1.7b # try another router model

Calls classify() alone — not the whole graph — so it runs in seconds, spends nothing on
answering, and touches no data. Prints accuracy, a confusion matrix, and every misroute with the
model's own reasoning, which is the field QueryClassification carries for exactly this purpose.

Read the misroutes, not just the score. A label in the test set can be wrong too, and a question
that two people would label differently is a question the prompt has to disambiguate.
"""
import argparse
import json
import pathlib
import sys
import time
from collections import Counter

from app.chat.classifier import classify
from app.chat.state import Category
from app.config import settings

QUESTIONS = pathlib.Path(__file__).resolve().parent.parent / "evals" / "classification_questions.json"
LABELS = [c.value for c in Category]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=["seen", "new", "all"], default="all")
    parser.add_argument("--model", help="override OLLAMA_MODEL for this run")
    parser.add_argument("--only", help="comma-separated question numbers, 1-based")
    args = parser.parse_args()

    if args.model:
        settings.ollama_model = args.model

    cases = json.loads(QUESTIONS.read_text())["questions"]
    if args.set != "all":
        cases = [c for c in cases if c["set"] == args.set]
    if args.only:
        wanted = {int(n) for n in args.only.split(",")}
        cases = [c for i, c in enumerate(cases, 1) if i in wanted]

    print(f"model: {settings.llm_backend} {settings.ollama_model} | set: {args.set} | "
          f"{len(cases)} questions | decline at >= {settings.decline_confidence}\n")

    confusion: Counter[tuple[str, str]] = Counter()
    misroutes: list[tuple[str, str, str, float, str]] = []
    secondary_hits = secondary_total = 0
    took: list[float] = []

    for case in cases:
        start = time.time()
        try:
            state = classify({"question": case["q"]})
            result = state["classification"]
        except Exception as exc:                       # noqa: BLE001 — a crash is a failure
            print(f"  ERROR  {case['q']}\n         {type(exc).__name__}: {exc}")
            confusion[(case["label"], "ERROR")] += 1
            continue
        took.append(time.time() - start)

        got = result.primary.value
        confusion[(case["label"], got)] += 1
        if got != case["label"]:
            misroutes.append((case["q"], case["label"], got, result.confidence, result.reasoning))

        if case.get("secondary"):
            secondary_total += 1
            if result.secondary and result.secondary.value == case["secondary"]:
                secondary_hits += 1

    correct = sum(n for (want, got), n in confusion.items() if want == got)
    total = sum(confusion.values())

    # ---------------------------------------------------------------- confusion matrix
    width = max(len(label) for label in LABELS) + 2
    print("confusion matrix — rows are the true label, columns what the model said\n")
    print(" " * width + "".join(f"{label[:9]:>11}" for label in LABELS))
    for want in LABELS:
        row = "".join(f"{confusion[(want, got)]:>11}" for got in LABELS)
        print(f"{want:<{width}}{row}")

    # ------------------------------------------------------------------ per class
    print("\nper class")
    for label in LABELS:
        true_positives = confusion[(label, label)]
        actual = sum(n for (want, _), n in confusion.items() if want == label)
        predicted = sum(n for (_, got), n in confusion.items() if got == label)
        recall = true_positives / actual if actual else 0.0
        precision = true_positives / predicted if predicted else 0.0
        print(f"  {label:<14} recall {recall:5.0%}  precision {precision:5.0%}  (n={actual})")

    # The expensive mistake: a real question turned away. Worth its own line, because it is the
    # failure a person notices and the reason decline_confidence sits above the floor.
    turned_away = sum(n for (want, got), n in confusion.items()
                      if got == Category.OUT_OF_SCOPE.value and want != Category.OUT_OF_SCOPE.value)

    if misroutes:
        print(f"\nmisroutes ({len(misroutes)})")
        for question, want, got, confidence, reasoning in misroutes:
            print(f"  {question}\n    wanted {want}, said {got} @{confidence:.2f} — {reasoning}")

    print(f"\naccuracy {correct}/{total} = {correct / total:.0%}"
          if total else "\nno questions ran")
    if secondary_total:
        print(f"second half caught {secondary_hits}/{secondary_total} on two-part questions")
    print(f"real questions turned away: {turned_away}")
    if took:
        print(f"median {sorted(took)[len(took) // 2]:.1f}s per question")

    return 0 if total and correct == total else 1


if __name__ == "__main__":
    sys.exit(main())
