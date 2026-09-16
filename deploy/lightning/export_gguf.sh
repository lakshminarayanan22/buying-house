#!/usr/bin/env bash
# Turn a trained adapter into a file Ollama can run, on the GPU machine rather than the laptop.
#
#   bash export_gguf.sh adapters/router-v1
#
# Three steps: fold the adapter into the base weights, convert to GGUF, quantise to Q4_K_M. Doing
# this here rather than on the Mac means downloading ~1.1 GB instead of ~3.4 GB, and no llama.cpp
# build on macOS.
set -euo pipefail

ADAPTER="${1:-adapters/router-v1}"
MERGED="${ADAPTER}-merged"
OUT="ecolink-router-q4_k_m.gguf"

python - "$ADAPTER" "$MERGED" <<'PY'
import sys
import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

adapter, merged = sys.argv[1], sys.argv[2]
base = AutoModelForCausalLM.from_pretrained(
    "Qwen/Qwen3-1.7B", torch_dtype=torch.float16, device_map="cpu")
model = PeftModel.from_pretrained(base, adapter).merge_and_unload()
model.save_pretrained(merged, safe_serialization=True)
AutoTokenizer.from_pretrained(adapter).save_pretrained(merged)
print(f"merged weights written to {merged}")
PY

if [ ! -d llama.cpp ]; then
  git clone --depth 1 https://github.com/ggml-org/llama.cpp
  pip install -r llama.cpp/requirements/requirements-convert_hf_to_gguf.txt
fi

python llama.cpp/convert_hf_to_gguf.py "$MERGED" --outfile router-f16.gguf --outtype f16

# The quantiser is a compiled tool; build only it, which takes about a minute.
cmake -S llama.cpp -B llama.cpp/build -DLLAMA_CURL=OFF >/dev/null
cmake --build llama.cpp/build --target llama-quantize -j >/dev/null
./llama.cpp/build/bin/llama-quantize router-f16.gguf "$OUT" Q4_K_M

ls -lh "$OUT"
echo "Download $OUT and the Modelfile, then on the Mac: ollama create ecolink-router -f Modelfile"
