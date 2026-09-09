"""Measure retrieval against a fixed question set.

Two numbers decide whether a change to chunking, the prefix or the model helped:

  recall@k   for answerable questions, did an expected chunk come back?
  refusals   for unanswerable ones, did the floor correctly return nothing?

The eval file is JSON:

    [
      {"q": "What machinery does Kovai run?", "expect": ["Mayer", "sinker"]},
      {"q": "What is Erode's dyeing capacity?", "expect": null}
    ]

`expect` is a list of substrings that must appear in at least one retrieved chunk, or null when
the corpus genuinely cannot answer and the right behaviour is to return nothing.
"""
import argparse
import json
import logging
import pathlib
import sys

from app.config import settings
from app.db import SessionLocal
from app.retrieval import search
from app.retrieval.embedding import active_model

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger("eval")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("questions", type=pathlib.Path)
    parser.add_argument("--top-k", type=int, default=settings.retrieval_top_k)
    parser.add_argument("--floor", type=float, default=settings.similarity_floor)
    parser.add_argument("--show-scores", action="store_true",
                        help="print top-1 similarity per question — use this to pick the floor")
    args = parser.parse_args()

    cases = json.loads(args.questions.read_text())
    log.info("%s questions · backend=%s (%s) · top_k=%s · floor=%.2f\n",
             len(cases), settings.embedding_backend, active_model(), args.top_k, args.floor)

    db = SessionLocal()
    answerable_hit = answerable_total = refused_ok = refused_total = 0
    try:
        for case in cases:
            hits = search(db, case["q"], top_k=args.top_k, floor=args.floor)
            top = hits[0].similarity if hits else 0.0

            if case.get("expect"):
                answerable_total += 1
                blob = " ".join(h.content for h in hits).lower()
                found = all(term.lower() in blob for term in case["expect"])
                answerable_hit += found
                mark = "hit " if found else "MISS"
                where = hits[0].citation if hits else "nothing returned"
            else:
                refused_total += 1
                correct = not hits
                refused_ok += correct
                mark = "ok  " if correct else "LEAK"
                where = "refused" if correct else f"returned {len(hits)}: {hits[0].citation}"

            score = f"  top1={top:.3f}" if args.show_scores else ""
            log.info("  %s %-58s %s%s", mark, case["q"][:58], where, score)

        log.info("")
        if answerable_total:
            log.info("recall@%s      %s/%s  (%.0f%%)", args.top_k, answerable_hit,
                     answerable_total, 100 * answerable_hit / answerable_total)
        if refused_total:
            log.info("refused right  %s/%s  (%.0f%%)", refused_ok, refused_total,
                     100 * refused_ok / refused_total)
    finally:
        db.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
