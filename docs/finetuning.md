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

## The SQL writer

A different shape from the router: instead of labelling examples, you correct queries. The model
drafts, you check the rows it returns, and your corrections become the training data.

### 1. Point the SQL step at XiYanSQL

In `backend/.env`:

```
OLLAMA_SQL_MODEL=hf.co/mradermacher/XiYanSQL-QwenCoder-7B-2504-GGUF:Q4_K_M
```

Without this the SQL step falls back to qwen3:8b **and a different prompt layout** — XiYanSQL
has its own template, and the app only uses it when this setting names a XiYan model. Draft with
one layout and serve the other and the fine-tune teaches a prompt your app never sends. The
trainer warns in its sidebar if this is not set.

### 2. Correct the drafts

```bash
cd ~/buying-house/backend
ollama serve &                                   # in its own tab
.venv/bin/pip install -e '.[trainer]'            # streamlit + pandas, once
.venv/bin/streamlit run trainer/app.py
```

A local tool, never deployed, that only ever touches `ecolink_eval` — your real data is not
reachable from it. Four tabs:

- **Review** — one question at a time. Press *Ask XiYanSQL for a draft* (20–40 seconds), read
  the SQL, press *Run it* to see the rows it returns on the evaluation database, then *Draft is
  right*, *Save correction* or *Skip*. An UPDATE or DELETE runs inside a transaction that is
  rolled back, so you see the real before-and-after without changing anything. The sidebar keeps
  a running figure for how often XiYanSQL was right unaided — the number that decides whether
  training is worth doing at all.
- **Database** — browse any table, and a scratchpad for running your own SELECT while you work
  out what the answer should be.
- **Creating records** — the 11 questions that ask the assistant to create something, and
  whether the app recognises them. No model call; it answers instantly.
- **Export** — how many corrections are ready, and which are excluded.

Corrections are saved to `backend/evals/sql_corrections.jsonl` as you go, one line per question.
Commit it: that file *is* the training data, and a diff shows exactly what you corrected.

### 3. Build the dataset

```bash
.venv/bin/python -m scripts.build_sql_dataset --dry-run    # look first
.venv/bin/python -m scripts.build_sql_dataset
```

Three rules decide what gets in: it must have been reviewed, it must still **run** against
`ecolink_eval` (checked again here, so a typo in a correction is caught now rather than an hour
into training), and it must not be one of the 40 scoring questions.

**The format** — `evals/training/sql_train.jsonl` and `sql_valid.jsonl`, one JSON object per line:

```json
{"messages": [
  {"role": "user", "content": "<the exact prompt the app sends: XiYan's template, the schema, the data notes, the question>"},
  {"role": "assistant", "content": "SELECT name, city FROM company WHERE status = 'LEAD' ORDER BY name"}
]}
```

One user turn, not a system/user pair, because XiYanSQL's template is a single block of text —
and the prompt is generated by the app's own `_sql_prompt`, so training input equals serving
input. Loss is taken on the assistant turn alone, so the model learns to write SQL rather than to
recite a schema it is handed anyway.

### 4. QLoRA, not LoRA — and why

**Use QLoRA.** It is not a close call on the hardware you have:

| | LoRA (16-bit base) | QLoRA (4-bit base) |
|---|---|---|
| A 7B model on a 16 GB T4 | ~16–20 GB — **does not fit** | ~8–10 GB — fits with room for a 2,048-token window |
| Quality, roughly | 90–95% of a full fine-tune | 80–90% |
| Lightning free tier | needs a 24 GB L4 or bigger | runs on the cheapest GPU |

The quality gap is real but small, and it is not what limits this job: with roughly 150 corrected
examples on one fixed schema, the data is the constraint, not the numeric precision of the frozen
weights. Spending a bigger GPU to close a few percent while the dataset is the bottleneck is the
wrong trade.

Worth revisiting only if the trained model scores close to XiYanSQL untrained *and* you want to
rule out quantisation as the reason: re-run the same dataset as 16-bit LoRA on an L4 and compare
on the held-out 40. That is a deliberate experiment, not a default.

### 5. Train on Lightning

Same Studio as the router. Upload `sql_train.jsonl`, `sql_valid.jsonl`, `deploy/lightning/`'s
`train_sql.py` and `requirements.txt`, switch the machine to a **T4**, then:

```bash
pip install -r requirements.txt
nvidia-smi                        # must show Tesla T4 before starting
python train_sql.py               # ~30-60 min for 150 examples
```

Base `XGenerationLab/XiYanSQL-QwenCoder-7B-2504` in 4-bit (NF4), LoRA r=16 on the attention and
MLP projections, 2 epochs, fp16 on a T4, gradient checkpointing, loss on the SQL only. It prints
ten generated queries beside your corrections at the end, so a broken run is obvious before you
export anything. Free studios restart every 4 hours; the script checkpoints each epoch and takes
`--resume`.

Then export, download and register it exactly as for the router, and point the app at it:

```
OLLAMA_SQL_MODEL=ecolink-sql
```

### 6. Keep it only if it wins

Score the trained model, XiYanSQL untrained and Qwen3-8B on the 40 held-out questions, comparing
the rows each query returns. Keep the new model only if it beats both.
