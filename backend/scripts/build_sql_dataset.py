"""Turn corrected SQL into training data for Lightning.

    .venv/bin/python -m scripts.build_sql_dataset            # after correcting in the trainer
    .venv/bin/python -m scripts.build_sql_dataset --dry-run  # check first, write nothing

Reads the corrections file the trainer writes (evals/sql_corrections.jsonl) and produces the two
files the Lightning script uploads. Three rules decide what gets in:

  1. **It must have been reviewed.** Anything still `todo`, or marked `skip`, is left out.
  2. **It must run.** Every query is re-executed against ecolink_eval before it is written; a
     correction with a typo is caught here rather than an hour into a training run.
  3. **It must not be a scoring question.** The 40 held-out questions never enter training —
     a model trained on the questions it is scored against tells you nothing.

The prompt in each example is the *exact* prompt production sends (`_sql_prompt`), so the model
is trained on the input it will be given. Train on a tidied-up prompt and you have fine-tuned a
model for a prompt your app never sends.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import random
import sys

from app.chat.branches import XIYAN_TEMPLATE, _data_notes, _schema_text, _sql_prompt
from app.chat.llm import uses_xiyan
from trainer import runner, store


def prompt_for(question: str, *, is_admin: bool, layout: str) -> str:
    """The prompt exactly as it will be sent at serving time.

    The layout matters more than it looks: XiYanSQL was trained on its own template, and the
    app switches to it only when OLLAMA_SQL_MODEL names a XiYan model. Build the dataset with
    one layout and serve the other, and the fine-tune is teaching a prompt the app never sends.
    """
    if layout == "auto":
        return _sql_prompt(question, is_admin=is_admin)
    if layout == "generic":
        permission = ("A change to the data is allowed if the question asks for one."
                      if is_admin else "Only a SELECT is allowed.")
        from app.chat.branches import _schema_prompt
        return ("Write exactly one PostgreSQL statement answering the question. Return only "
                "SQL, no prose and no markdown fence.\n" + f"{permission}\n"
                + f"\nSchema:\n{_schema_prompt()}\n\nQuestion: {question}")
    permission = ("A change to the data is allowed if the question asks for one." if is_admin
                  else "Only a SELECT is allowed.")
    return XIYAN_TEMPLATE.format(dialect="PostgreSQL", question=question,
                                 db_schema=_schema_text(),
                                 evidence=f"{_data_notes()}\n- {permission}")


def example(question: str, sql: str, *, is_admin: bool, layout: str) -> dict:
    """One training row: the production prompt in, the corrected SQL out.

    A single user turn rather than a system/user pair, because XiYanSQL's own template — the
    layout it was trained on — is one block of text. Loss is taken on the assistant turn alone
    (completion_only_loss in the trainer), so the model learns to write SQL, not to recite a
    schema it is handed anyway.
    """
    return {"messages": [
        {"role": "user", "content": prompt_for(question, is_admin=is_admin, layout=layout)},
        {"role": "assistant", "content": sql.strip()},
    ]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corrections", type=pathlib.Path, default=store.CORRECTIONS)
    parser.add_argument("--out-dir", type=pathlib.Path, default=store.BACKEND / "evals" / "training")
    parser.add_argument("--valid-fraction", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=20260923)
    parser.add_argument("--prompt", choices=["xiyan", "generic", "auto"], default="xiyan",
                        help="which prompt layout to train on. Default xiyan: the model being "
                             "fine-tuned is XiYanSQL, and it must be served the same way.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-check", action="store_true",
                        help="do not re-run each query (faster, and trusts the file)")
    args = parser.parse_args()

    if not args.corrections.exists():
        print(f"No corrections yet at {args.corrections}. Correct some in the trainer first:\n"
              f"  .venv/bin/streamlit run trainer/sql_trainer.py")
        return 1

    questions = {q["id"]: q for q in store.questions()}
    scoring = {q["id"] for q in questions.values() if q["set"] == "score"}
    saved = {}
    for line in args.corrections.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            saved[row["id"]] = row

    rows, skipped, broken = [], [], []
    for row_id, row in sorted(saved.items()):
        if row["status"] not in ("ok", "fixed", "rewritten") or not row.get("final_sql", "").strip():
            skipped.append((row_id, row["status"]))
            continue
        if row_id in scoring:
            skipped.append((row_id, "held out for scoring"))
            continue
        question = questions.get(row_id)
        if question is None:
            skipped.append((row_id, "not in the question set"))
            continue

        is_admin = question["kind"] == "write"
        if not args.skip_check:
            result = runner.run(row["final_sql"], allow_write=is_admin)
            if not result.ok:
                broken.append((row_id, result.error[:90]))
                continue
        rows.append(example(question["q"], row["final_sql"], is_admin=is_admin,
                            layout=args.prompt))

    print(f"prompt layout: {args.prompt}"
          + ("  (serving uses XiYan's template — OLLAMA_SQL_MODEL names a XiYan model)"
             if uses_xiyan() else
             "  ⚠ serving is NOT using XiYan's template right now: set OLLAMA_SQL_MODEL in .env "
             "to the model you will serve, or the app will prompt differently from training"))
    print(f"{len(rows)} usable · {len(skipped)} left out · {len(broken)} did not run")
    for row_id, why in broken:
        print(f"  BROKEN {row_id}: {why}")
    if broken:
        print("Fix those in the trainer — a query that does not run teaches the model nothing.")
    if not rows:
        return 1

    counts: dict[str, int] = {}
    for row in rows:
        kind = row["messages"][1]["content"].strip().split()[0].upper()
        counts[kind] = counts.get(kind, 0) + 1
    print("by statement:", counts)

    if args.dry_run:
        print("\n--dry-run: nothing written. First example:\n")
        print(rows[0]["messages"][0]["content"][:400], "…\n→", rows[0]["messages"][1]["content"])
        return 0

    random.Random(args.seed).shuffle(rows)
    split = max(1, int(len(rows) * args.valid_fraction))
    args.out_dir.mkdir(parents=True, exist_ok=True)
    for name, part in (("train", rows[split:]), ("valid", rows[:split])):
        path = args.out_dir / f"sql_{name}.jsonl"
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in part))
        print(f"{path.relative_to(store.BACKEND)}: {len(part)} examples")
    print("\nUpload those two files to the Lightning Studio — see docs/finetuning.md.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
