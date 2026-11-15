"""Letter-only accuracy of the base model and/or the LoRA adapter on any problems file,
with exactly the evaluate() used during training (board prompt, A-E only, greedy).

  python finetune/eval_hf.py --input data/demo/train.jsonl            # base + ft-v1 adapter
  python finetune/eval_hf.py --input data/demo/train.jsonl --only base
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import train_lora as tl  # noqa: E402  (same prompt, tokenizer handling and evaluate())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--adapter", default=os.path.join(tl.ROOT, "work", "fine_tuner", "lora_ft-v1"))
    p.add_argument("--only", choices=["base", "ft"], default=None)
    p.add_argument("--out", default=None, help="write the metrics JSON here")
    args = p.parse_args()

    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    problems = [json.loads(l) for l in open(args.input, encoding="utf-8") if l.strip()]
    tok = AutoTokenizer.from_pretrained(tl.BASE_MODEL, revision=tl.BASE_REVISION)
    if tok.pad_token is None:
        tok.pad_token = tok.eos_token
    letter_ids = torch.tensor([tok.encode(L, add_special_tokens=False)[0] for L in tl.LETTERS], device=tl.DEVICE)
    log = tl.Log(None)
    model = AutoModelForCausalLM.from_pretrained(tl.BASE_MODEL, revision=tl.BASE_REVISION,
                                                 dtype=torch.bfloat16).to(tl.DEVICE)
    results = {}
    if args.only in (None, "base"):
        results["base"] = tl.evaluate(model, tok, problems, letter_ids, 4, 512, "base", log)
    if args.only in (None, "ft"):
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, args.adapter)
        results["finetuned"] = tl.evaluate(model, tok, problems, letter_ids, 4, 512, "finetuned", log)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=1)


if __name__ == "__main__":
    main()
