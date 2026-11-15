"""Merge the OCR improver's repaired options into new data files.

Never overwrites the originals. Writes data/train_fixed.jsonl and data/val_fixed.jsonl
plus a report of what changed, for the validator to check.

  python orchestration/apply_fixes.py --fixes work/ocr_improver/fixes.jsonl --min-confidence 0.8

Each fix line looks like {"key": "id|lang", "options": {...} or {}, "confidence": 0.9, "reason": "..."}.
A fix is used only when it has exactly A-E with five non-empty, distinct values.
"""
import argparse
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LETTERS = "ABCDE"


def valid(options):
    return (isinstance(options, dict) and sorted(options) == list(LETTERS)
            and all(str(v).strip() for v in options.values())
            and len({str(v).strip() for v in options.values()}) == 5)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--fixes", default=os.path.join(ROOT, "work", "ocr_improver", "fixes.jsonl"))
    p.add_argument("--min-confidence", type=float, default=0.8)
    p.add_argument("--min-confidence-picture", type=float, default=0.9,
                   help="stricter bar for fixes whose options describe pictures (kind == \"picture\")")
    p.add_argument("--splits", default="train,val")
    args = p.parse_args()

    fixes = {}
    with open(args.fixes, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            bar = args.min_confidence_picture if row.get("kind") == "picture" else args.min_confidence
            if row.get("confidence", 0) >= bar and valid(row.get("options")):
                fixes[row["key"]] = row

    report = []
    for split in args.splits.split(","):
        src = os.path.join(ROOT, "data", f"{split}.jsonl")
        dst = os.path.join(ROOT, "data", f"{split}_fixed.jsonl")
        if not os.path.exists(src):
            print(f"skip {split}: {src} not found (run laptop/prepare_m3kang.py first)")
            continue
        changed = total = before = after = 0
        with open(src, encoding="utf-8") as f, open(dst, "w", encoding="utf-8") as out:
            for line in f:
                row = json.loads(line)
                total += 1
                before += bool(row.get("options"))
                fix = fixes.get(f"{row['id']}|{row['language']}")
                if fix and {k: str(v).strip() for k, v in fix["options"].items()} != row.get("options"):
                    report.append({"split": split, "key": f"{row['id']}|{row['language']}",
                                   "old": row.get("options"), "new": fix["options"],
                                   "kind": fix.get("kind", "text"),
                                   "confidence": fix.get("confidence"), "reason": fix.get("reason", "")})
                    row["options"] = {k: str(fix["options"][k]).strip() for k in LETTERS}
                    row["options_source"] = "ocr_improver"
                    changed += 1
                after += bool(row.get("options"))
                out.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"{split}: {changed}/{total} changed, problems with options {before} -> {after}  ({dst})")

    rep = os.path.join(ROOT, "work", "ocr_improver", "applied_report.jsonl")
    os.makedirs(os.path.dirname(rep), exist_ok=True)
    with open(rep, "w", encoding="utf-8") as f:
        for r in report:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"Changes listed in {rep}")


if __name__ == "__main__":
    main()
