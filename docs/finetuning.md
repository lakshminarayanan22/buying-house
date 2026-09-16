# Fine-tuning the Ask box

Training runs **on a rented GPU, never on the laptop**. The Mac builds a JSONL file, uploads it,
and later downloads one file.

**Where:** a **Lightning AI Studio**. Modal was the first choice and its script is still in
`deploy/modal/`, but Modal refuses GPU functions until a card is on file — "Please add a payment
method to use L4 GPU functions" — so it is unusable without one. Lightning's free tier gives a
studio plus around 15 credits a month (roughly 20+ T4 hours) with **no card**, and this job needs
well under an hour. The training script is plain Python, so it also runs unchanged on Colab or
Kaggle if the free hours run out.

There are two models worth training, in this order:

1. **The router** — picks DATABASE / TECHNICAL / CREATIVE / OUT_OF_SCOPE. Cheap, quick, and the
   thing that misroutes today. Covered in full below.
2. **The SQL writer** — XiYanSQL. Needs verified (question, SQL) pairs and is a bigger job; it
   reuses everything here, and its section is at the end.

---

## First: check whether you need to train at all

The prompt now has a fourth category and a decline path. Measure before spending anything:

```bash
cd ~/buying-house/backend
ollama serve &                                          # the local model, for the baseline only
.venv/bin/python -m scripts.eval_classify --set new     # the half never used for tuning
```

Use `.venv/bin/python`, not `python`. The backend's dependencies live in that virtualenv and
there is no `python` on the PATH of a fresh shell — `python3` would run the system interpreter,
which has none of them.

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
cd ~/buying-house/backend
.venv/bin/python -m scripts.build_classifier_dataset    # ~880 examples
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
head -5 evals/training/classifier_train.jsonl | .venv/bin/python -m json.tool
```

---

## Training on Lightning

**Once:** sign up at lightning.ai (no card), and create a Studio. It starts on a free CPU
machine; you switch to a GPU only while training, from the machine selector at the top right.
Watch the credit meter — a T4 is about 1 credit an hour and this job needs well under one.

**Upload four files** into the Studio by dragging them onto its file browser:

- `backend/evals/training/classifier_train.jsonl`
- `backend/evals/training/classifier_valid.jsonl`
- `deploy/lightning/train_classifier.py`
- `deploy/lightning/requirements.txt`

**Then, in the Studio's terminal** — switch the machine to a **T4** first:

```bash
pip install -r requirements.txt
python train_classifier.py          # ~20-30 min on a T4
```

It prints the validation loss per epoch and then asks the trained router six probe questions,
including ones no training row contains. Loss curves don't tell you whether it routes; those
answers do.

What it does: LoRA (r=16) on **Qwen3-1.7B**, 3 epochs, half precision, gradient checkpointing so
it fits a 16 GB card. Loss is computed on the answer only — the system prompt is the category
definitions repeated on every row, and training on it would teach the model to recite the prompt.
The script asks the card whether it supports bf16 rather than assuming, because T4s do not.

To try different settings, keep the first adapter by naming the output:

```bash
python train_classifier.py --epochs 4 --lr 5e-5 --out adapters/router-v2
```

**Turn the GPU machine back off when the run finishes.** An idle studio on a GPU spends credits
for nothing.

---

## Getting it back and using it

Do the conversion in the Studio, not on the Mac: it turns a 3.4 GB download into a 1.1 GB one,
and avoids building llama.cpp on macOS. Upload `deploy/lightning/export_gguf.sh` alongside the
rest, then:

```bash
bash export_gguf.sh adapters/router-v1      # merge → GGUF → quantise to Q4_K_M
```

Download the resulting `ecolink-router-q4_k_m.gguf`, put it beside `deploy/lightning/Modelfile`
on the Mac, and register it:

```bash
ollama create ecolink-router -f Modelfile
```

Then point the app at it — **no code change**, because the model is already a setting:

```
CLASSIFIER_MODEL=ecolink-router
```

Note for later: the deployment plan plans to serve XiYanSQL from Ollama **on Modal**, which hits
the same card requirement. That decision needs revisiting when it is time to deploy — it does not
block anything here.

---

## Keep it only if it wins

```bash
cd ~/buying-house/backend
.venv/bin/python -m scripts.eval_classify --set new --model ecolink-router  # the trained router
.venv/bin/python -m scripts.eval_classify --set new --model qwen3:8b       # the baseline to beat
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
- **Hardware:** a 7B LoRA needs more than a T4 — an L4 or A10G, 2–3 epochs, 1–2 hours. On
  Lightning's free credits that is most of a month's allowance, so this is the one to think about
  before starting.
- **The rule:** the 18 `new` questions in `evals/sql_questions.json` never enter training, just
  as the `new` routing questions never do here.
- **Scoring:** `.venv/bin/python -m scripts.eval_sql` against the baseline of 18/30 overall and
  10/18 on the unseen half.
