"""Merge the LoRA adapter from train_lora.py into the base weights.

Loads the original HF checkpoint in bf16 on the CPU (no training is running at this
point, and merging on the CPU keeps the GPU free and is deterministic), checks that the
merged model picks the same letters as the adapter on a handful of training prompts,
then writes a plain HF folder that convert_hf_to_gguf.py can read:

  python finetune/merge_lora.py --version ft-v1
  -> work/fine_tuner/merged_ft-v1/

Runs in about two minutes; needs ~4 GB of RAM, no GPU.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
from copilot.llm import SYSTEM  # noqa: E402

# Same constant as finetune/train_lora.py: the original HF checkpoint, NOT the GGUF.
# CONFIRM THIS REPO ID ON huggingface.co BEFORE RUNNING.
BASE_MODEL = "Qwen/Qwen3.5-0.8B"  # verified on huggingface.co: base of the board's GGUF
BASE_REVISION = "2fc06364715b967f1860aea9cf38778875588b17"  # pinned, like the other models in config.env
LETTERS = "ABCDE"


@torch.no_grad()

def _chat_ids(tok, messages, **kw):
    """Token ids from apply_chat_template: transformers 5 returns a BatchEncoding (dict-like),
    older versions a plain list. list() of the dict would give its key names."""
    out = tok.apply_chat_template(messages, **kw)
    if hasattr(out, "keys") and "input_ids" in out:
        out = out["input_ids"]
    return list(out)

def sample_letters(model, tok, users, letter_ids):
    preds = []
    for user in users:
        msgs = [{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}]
        ids = _chat_ids(tok, msgs, tokenize=True, add_generation_prompt=True)
        out = model(input_ids=torch.tensor([ids], dtype=torch.long))
        last = out.logits[0, -1]
        preds.append(LETTERS[int(last.index_select(0, letter_ids).argmax())])
    return preds


def main():
    ap = argparse.ArgumentParser(description="Merge a LoRA adapter into the base weights")
    ap.add_argument("--base", default=BASE_MODEL)
    ap.add_argument("--adapter", default=os.path.join(ROOT, "work", "fine_tuner", "lora_ft-v1"))
    ap.add_argument("--out", default=os.path.join(ROOT, "work", "fine_tuner", "merged_ft-v1"))
    ap.add_argument("--dtype", default="bfloat16", choices=["bfloat16", "float16", "float32"])
    ap.add_argument("--check-samples", type=int, default=5,
                    help="training prompts used to verify adapter == merged (0 disables)")
    ap.add_argument("--sft", default=os.path.join(ROOT, "work", "fine_tuner", "sft.jsonl"))
    args = ap.parse_args()

    if not os.path.isdir(args.adapter):
        raise SystemExit(f"adapter not found: {args.adapter} (run finetune/train_lora.py first)")
    dtype = getattr(torch, args.dtype)
    t0 = time.time()

    tok = AutoTokenizer.from_pretrained(args.adapter)
    print(f"loading {args.base} in {args.dtype} on CPU ...", flush=True)
    model = AutoModelForCausalLM.from_pretrained(
        args.base, revision=BASE_REVISION, torch_dtype=dtype, low_cpu_mem_usage=True, device_map="cpu")
    model = PeftModel.from_pretrained(model, args.adapter)

    # ---- sanity check: the merged weights must be behaviourally identical ----------
    if args.check_samples:
        users = []
        with open(args.sft, encoding="utf-8") as f:
            for line in f:
                users.append(json.loads(line)["messages"][1]["content"])
                if len(users) >= args.check_samples:
                    break
        letter_ids = torch.tensor([tok.encode(L, add_special_tokens=False)[0] for L in LETTERS])
        before = sample_letters(model, tok, users, letter_ids)
        print(f"adapter predictions on {len(users)} prompts: {''.join(before)}", flush=True)

    print("merging ...", flush=True)
    merged = model.merge_and_unload()

    if args.check_samples:
        after = sample_letters(merged, tok, users, letter_ids)
        print(f"merged  predictions on {len(users)} prompts: {''.join(after)}", flush=True)
        if before != after:
            raise SystemExit("merged model disagrees with the adapter; do not convert this folder")

    os.makedirs(args.out, exist_ok=True)
    merged.save_pretrained(args.out, safe_serialization=True, max_shard_size="2GB")
    tok.save_pretrained(args.out)
    with open(os.path.join(args.out, "merge_info.json"), "w", encoding="utf-8") as f:
        json.dump({"base_model": args.base, "base_model_confirmed": False,
                   "adapter": os.path.relpath(args.adapter, ROOT),
                   "dtype": args.dtype, "seconds": round(time.time() - t0, 1)},
                  f, indent=2)

    total = sum(os.path.getsize(os.path.join(args.out, n))
                for n in os.listdir(args.out) if n.endswith((".safetensors", ".bin")))
    print(f"merged model written to {args.out} ({total / 1e9:.2f} GB, "
          f"{time.time() - t0:.0f} s)")
    print("next: pwsh -File finetune/convert_gguf.ps1 "
          f"-MergedDir {os.path.relpath(args.out, ROOT)} -Version ft-v1")


if __name__ == "__main__":
    main()
