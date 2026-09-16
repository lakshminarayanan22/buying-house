# Fine-tuning the Ask box

Training runs **on Modal only**. Nothing here trains on the laptop: the Mac builds a JSONL file,
uploads it, and later downloads an adapter of a few megabytes. The GPU work happens remotely and
stops when the job ends.

There are two models worth training, in this order:

1. **The router** — picks DATABASE / TECHNICAL / CREATIVE / OUT_OF_SCOPE. Cheap, quick, and the
   thing that misroutes today. Covered in full below.
2. **The SQL writer** — XiYanSQL. Needs verified (question, SQL) pairs and is a bigger job; it
   reuses everything here, and its section is at the end.

---

## First: check whether you need to train at all

The prompt now has a fourth category and a decline path. Measure before spending anything:

```bash
cd backend
ollama serve &                                   # the local model, for the baseline only
python -m scripts.eval_classify --set new        # the half never used for tuning
```

You get a confusion matrix, per-class recall and precision, every misroute with the model's own
reasoning, and a count of **real questions turned away** — the expensive mistake.

**If accuracy on `--set new` is 95% or better and nothing real was turned away, stop here.** The
prompt is doing the job and a fine-tune would cost money to match it. A six-question spot check
after the prompt change scored 6/6, so this is a real possibility.

Train when: accuracy is below that, the same confusion repeats (usually DATABASE vs TECHNICAL),
or you want the router on a 1.7B model so it answers in a fraction of a second instead of four.

---

## The data

```bash
cd backend
python -m scripts.build_classifier_dataset          # ~880 examples
```

Writes `evals/training/classifier_train.jsonl` and `classifier_valid.jsonl`, from two sources:

- The **84 hand-labelled `seen`** questions in `evals/classification_questions.json`.
- **Templates crossed with the trade's vocabulary** — mills in Tiruppur, Karur, Ludhiana and
  Dhaka, organic cotton, recycled polyester, denim, buyers in Germany and Japan. Most of these
  are deals we do not have. That is deliberate: routing must not depend on which companies
  happen to be in the database, and a router that has only seen Erode and Kaimei learns those
  names instead of the shape of a question.

**The 81 `new` questions are never written into training data**, and the script refuses to run
if any leaks in. That split is the only honest measure you have; training on it turns the score
into a measure of memory.

Read a sample before uploading — bad labels train faster than good ones:

```bash
head -5 evals/training/classifier_train.jsonl | python -m json.tool
```

---

## Modal setup, once

1. **Account and CLI** — sign up at modal.com (Starter includes **$30/month of free compute**),
   then on the Mac:
   ```bash
   pip install modal
   modal setup                    # opens a browser, writes a token to ~/.modal.toml
   ```
2. **Spending guard** — set a budget alert in the Modal dashboard. Nothing here should approach
   the free credit, and an alert catches a job left running.
3. Nothing else. The volume (`ecolink-training`) is created on first use, and the base weights
   download themselves inside Modal.

---

## Training

```bash
cd ~/buying-house                # run from the repo root, not backend/

modal run deploy/modal/train_classifier.py::upload_data
modal run deploy/modal/train_classifier.py::run_training          # ~15 min on an L4
```

`run_training` trains and then prints the trained router's answers to six probe questions,
including ones it never saw. Loss curves don't tell you whether it routes; those answers do.

What it does: LoRA (r=16) on **Qwen3-1.7B**, 3 epochs, bf16, on one L4. Loss is computed on the
answer only — the system prompt is the category definitions repeated on every row, and training
on it would teach the model to recite the prompt.

Roughly **$0.20 per run** ($0.80/hr for the L4), well inside the free credit. To try again with
different settings, use a new run name so the first adapter survives:

```bash
modal run deploy/modal/train_classifier.py::run_training --epochs 4 --run v2
```

---

## Getting it back and using it

```bash
modal run deploy/modal/train_classifier.py::download --run v1     # → artifacts/router/v1/
```

To serve it, the adapter is fused into the base weights, converted to GGUF with llama.cpp, and
registered with Ollama:

```bash
ollama create ecolink-router -f Modelfile
```

Then point the app at it — **no code change**, because the model is already an env var:

```
CLASSIFIER_MODEL=ecolink-router
```

In production the same model runs in the Ollama container on Modal, beside XiYanSQL.

---

## Keep it only if it wins

```bash
cd backend
python -m scripts.eval_classify --set new                # trained router
python -m scripts.eval_classify --set new --model qwen3:8b   # the baseline it must beat
```

Compare the confusion matrices, not just the accuracy. A model that gains two points overall
while turning away a real question is worse for the people using it. If it doesn't beat the
prompt version, delete the adapter and write down what you tried — that result is worth as much
as a win, and cost twenty cents.

---

## Later: the SQL writer

Same Modal setup, a bigger job.

- **Base model:** `XiYanSQL-QwenCoder-7B-2504`, already chosen for the SQL step.
- **Data, and the part that matters:** generate (question, SQL) pairs from the schema, then
  **execute every one against the dev database and keep only those that run and return the
  expected answer**. An LLM writing SQL that looks right is not evidence; the database is.
  Target 300–800 verified pairs.
- **Hardware:** an A10G, 2–3 epochs, 1–2 hours, roughly **$2–4**.
- **The rule:** the 18 `new` questions in `evals/sql_questions.json` never enter training, just
  as the `new` routing questions never do here.
- **Scoring:** `python -m scripts.eval_sql` against the baseline of 18/30 overall and 10/18 on
  the unseen half.
