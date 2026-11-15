"""Turn the improved training data into a chat-format fine-tuning set for Qwen3.5 0.8B.

Uses exactly the same system prompt and problem formatting as copilot/llm.py, so the
fine-tuned model sees at training time what it will see on the board. The target is the
single letter, as the board forces it with the grammar.

  python orchestration/build_ft_dataset.py --input data/train.jsonl --out work/fine_tuner/sft.jsonl

Optional: --rationales work/fine_tuner/rationales.jsonl (from the fine_tuner batch role)
adds a second copy of each problem whose target is a short solution then the letter.
Only use it if the board pipeline is changed to allow a few reasoning tokens.

Never builds from val: validation must stay unseen.
"""
import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from copilot.llm import SYSTEM, format_problem  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--input", default=os.path.join(ROOT, "data", "train.jsonl"))
    p.add_argument("--out", default=os.path.join(ROOT, "work", "fine_tuner", "sft.jsonl"))
    p.add_argument("--only-with-options", action="store_true")
    p.add_argument("--rationales")
    args = p.parse_args()
    if "val" in os.path.basename(args.input):
        raise SystemExit("Refusing to fine-tune on validation data.")

    rationales = {}
    if args.rationales:
        with open(args.rationales, encoding="utf-8") as f:
            for line in f:
                r = json.loads(line)
                if r.get("ok", True) and r.get("rationale") and r.get("answer"):
                    rationales[r["key"]] = r

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    n = 0
    with open(args.input, encoding="utf-8") as f, open(args.out, "w", encoding="utf-8") as out:
        for line in f:
            prob = json.loads(line)
            if args.only_with_options and not prob.get("options"):
                continue
            user = format_problem(prob) + "\nAnswer:"
            out.write(json.dumps({"messages": [{"role": "system", "content": SYSTEM},
                                               {"role": "user", "content": user},
                                               {"role": "assistant", "content": prob["label"]}]},
                                 ensure_ascii=False) + "\n")
            n += 1
            r = rationales.get(f"{prob['id']}|{prob['language']}")
            if r and r["answer"] == prob["label"]:
                out.write(json.dumps({"messages": [{"role": "system", "content": SYSTEM},
                                                   {"role": "user", "content": user},
                                                   {"role": "assistant",
                                                    "content": f"{r['rationale'].strip()}\n{prob['label']}"}]},
                                     ensure_ascii=False) + "\n")
                n += 1
    print(f"Wrote {n} examples to {args.out}")


if __name__ == "__main__":
    main()
