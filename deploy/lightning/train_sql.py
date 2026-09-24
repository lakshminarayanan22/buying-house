"""QLoRA fine-tune of the SQL writer. Runs on any machine with an NVIDIA GPU.

Written for a Lightning AI Studio on a 16 GB T4 — nothing trains on the laptop. It is plain
Python, so it runs unchanged on Colab or Kaggle if the free hours run out.

    pip install -r requirements.txt
    nvidia-smi                       # confirm a GPU is attached before starting
    python train_sql.py

**QLoRA, not LoRA, and not by preference.** A 7B model in 16-bit needs roughly 16-20 GB just for
weights and does not fit a T4; loaded in 4-bit it takes 8-10 GB and leaves room for a 2,048-token
window. The quality gap is a few percent, and with fifty-odd corrected examples on one schema the
dataset is the constraint, not the numeric precision of frozen weights.

The dataset is what a person corrected in trainer/sql_trainer.py, built by
scripts/build_sql_dataset.py: each row is the exact prompt the app sends paired with the SQL that
was verified to run. Loss is taken on the SQL alone — the prompt carries the whole schema, and
training on it would teach the model to recite a schema it is handed anyway.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import time

import torch
from datasets import Dataset
from peft import LoraConfig, prepare_model_for_kbit_training
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from trl import SFTConfig, SFTTrainer

BASE_MODEL = "XGenerationLab/XiYanSQL-QwenCoder-7B-2504"


def read_jsonl(path: pathlib.Path) -> Dataset:
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not rows:
        raise SystemExit(f"{path} is empty — run scripts.build_sql_dataset first")
    return Dataset.from_list(rows)


def probe(model, tokenizer, examples: list[dict]) -> None:
    """Generate SQL for a few validation prompts and print it beside the corrected version.

    Loss going down says the model is fitting something. Only the queries say whether it writes
    SQL you would accept.
    """
    model.eval()
    print("\n" + "=" * 78)
    for row in examples[:8]:
        prompt, gold = row["messages"][0]["content"], row["messages"][1]["content"]
        text = tokenizer.apply_chat_template([{"role": "user", "content": prompt}],
                                             tokenize=False, add_generation_prompt=True)
        inputs = tokenizer(text, return_tensors="pt").to(model.device)
        with torch.no_grad():
            out = model.generate(**inputs, max_new_tokens=200, do_sample=False,
                                 pad_token_id=tokenizer.eos_token_id)
        said = tokenizer.decode(out[0][inputs["input_ids"].shape[1]:],
                                skip_special_tokens=True).strip()
        question = prompt.split("【用户问题】")[1].split("\n")[1] if "【用户问题】" in prompt \
            else prompt[-120:]
        print(f"Q: {question.strip()}")
        print(f"  trained: {said.splitlines()[0][:150] if said else '(nothing)'}")
        print(f"  yours:   {gold.splitlines()[0][:150]}")
    print("=" * 78 + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", default="sql_train.jsonl")
    parser.add_argument("--valid", default="sql_valid.jsonl")
    parser.add_argument("--out", default="adapters/sql-v1")
    parser.add_argument("--base", default=BASE_MODEL)
    parser.add_argument("--epochs", type=float, default=3)
    parser.add_argument("--lr", type=float, default=1e-4)
    parser.add_argument("--batch", type=int, default=1)
    parser.add_argument("--grad-accum", type=int, default=16)
    # The prompt carries the schema and the data notes: about 1,900 tokens before the question.
    parser.add_argument("--max-length", type=int, default=2560)
    parser.add_argument("--max-steps", type=int, default=-1,
                        help="stop after N steps — use 20 for a first run, to prove it fits")
    parser.add_argument("--resume", action="store_true",
                        help="continue from the last checkpoint (free studios restart every 4h)")
    args = parser.parse_args()

    if not torch.cuda.is_available():
        raise SystemExit("No GPU visible. Switch the Studio's machine to a T4 and run again.")

    bf16 = torch.cuda.is_bf16_supported()      # T4s do not; ask rather than assume
    print(f"{torch.cuda.get_device_name(0)} · {'bf16' if bf16 else 'fp16'} · 4-bit base")

    train_ds = read_jsonl(pathlib.Path(args.train))
    valid_rows = [json.loads(l) for l in pathlib.Path(args.valid).read_text().splitlines() if l.strip()]
    valid_ds = Dataset.from_list(valid_rows)
    print(f"{len(train_ds)} training examples, {len(valid_ds)} validation")
    if len(train_ds) < 40:
        print("Note: a small dataset. Expect a modest change, and compare against the "
              "untrained model on the held-out questions before keeping this.")

    tokenizer = AutoTokenizer.from_pretrained(args.base)
    model = AutoModelForCausalLM.from_pretrained(
        args.base,
        quantization_config=BitsAndBytesConfig(
            load_in_4bit=True,
            bnb_4bit_quant_type="nf4",
            bnb_4bit_use_double_quant=True,
            bnb_4bit_compute_dtype=torch.bfloat16 if bf16 else torch.float16,
        ),
        device_map="cuda",
    )
    model = prepare_model_for_kbit_training(model, use_gradient_checkpointing=True)
    model.config.use_cache = False

    trainer = SFTTrainer(
        model=model,
        train_dataset=train_ds,
        eval_dataset=valid_ds,
        processing_class=tokenizer,
        peft_config=LoraConfig(
            r=16, lora_alpha=32, lora_dropout=0.05, bias="none", task_type="CAUSAL_LM",
            target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                            "gate_proj", "up_proj", "down_proj"],
        ),
        args=SFTConfig(
            output_dir=args.out,
            num_train_epochs=args.epochs,
            max_steps=args.max_steps,
            per_device_train_batch_size=args.batch,
            gradient_accumulation_steps=args.grad_accum,
            gradient_checkpointing=True,
            learning_rate=args.lr,
            lr_scheduler_type="cosine",
            warmup_ratio=0.05,
            logging_steps=5,
            eval_strategy="epoch",
            save_strategy="epoch",
            save_total_limit=2,
            bf16=bf16,
            fp16=not bf16,
            max_length=args.max_length,
            completion_only_loss=True,
            report_to=[],
        ),
    )

    started = time.time()
    trainer.train(resume_from_checkpoint=args.resume or None)
    trainer.save_model(args.out)
    tokenizer.save_pretrained(args.out)
    print(f"\nadapter saved to {args.out} — {(time.time() - started) / 60:.1f} minutes")
    for entry in trainer.state.log_history:
        if "eval_loss" in entry:
            print(f"  epoch {entry['epoch']:.0f}  validation loss {entry['eval_loss']:.4f}")

    probe(trainer.model, tokenizer, valid_rows)
    print("Next: bash export_gguf.sh", args.out,
          "XGenerationLab/XiYanSQL-QwenCoder-7B-2504 ecolink-xiyan-sql")


if __name__ == "__main__":
    main()
