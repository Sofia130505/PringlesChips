"""Compare a candidate prepare_m3kang.py against the current parser, on the same problems.

  python orchestration/eval_parser.py work/ocr_improver/parser-v2/files/laptop/prepare_m3kang.py --limit 400

Runs the candidate on a copy (its own temp output folder and OCR cache, never data/), then reports:
  (a) problems with options: current parser vs candidate, on the same problems
  (b) agreement with silver labels: the OCR improver's validated text fixes (kind text, confidence >= 0.9),
      exact match after whitespace normalisation
  (c) regressions: problems the current parser read that the candidate loses or changes
Current-parser options come from data/train.jsonl + data/val.jsonl (same OCR, same shard).
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def norm(options):
    return {k: re.sub(r"\s+", "", str(v)).lower() for k, v in (options or {}).items()}


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("candidate", help="path to the candidate prepare_m3kang.py")
    p.add_argument("--languages", default="eng")
    p.add_argument("--limit", type=int, default=400)
    p.add_argument("--keep", action="store_true", help="keep the temp output folder")
    args = p.parse_args()

    tmp = tempfile.mkdtemp(prefix="parser_eval_")
    try:
        # The candidate runs from a copy inside tmp, so nothing in the repo is touched.
        script = os.path.join(tmp, "prepare_candidate.py")
        shutil.copy(args.candidate, script)
        # Helper modules next to the candidate (e.g. option_parser.py) come along.
        cand_dir = os.path.dirname(os.path.abspath(args.candidate))
        for name in os.listdir(cand_dir):
            if name.endswith(".py") and name != os.path.basename(args.candidate):
                shutil.copy(os.path.join(cand_dir, name), os.path.join(tmp, name))
        out = os.path.join(tmp, "out")
        env = {**os.environ, "PYTHONUTF8": "1", "HF_HUB_DISABLE_SYMLINKS_WARNING": "1"}
        cmd = [sys.executable, script, "--languages", args.languages, "--limit", str(args.limit), "--out", out]
        print("running:", " ".join(cmd), flush=True)
        run = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        tail = [l for l in run.stdout.splitlines() if l.strip()][-6:]
        print("\n".join("  | " + l for l in tail))
        if run.returncode != 0:
            print(run.stderr[-3000:])
            sys.exit(f"candidate failed with exit code {run.returncode}")

        cand = {f"{r['id']}|{r['language']}": r.get("options") or {}
                for split in ("train", "val") if os.path.exists(os.path.join(out, f"{split}.jsonl"))
                for r in load_jsonl(os.path.join(out, f"{split}.jsonl"))}
        cur = {f"{r['id']}|{r['language']}": r.get("options") or {}
               for split in ("train", "val") for r in load_jsonl(os.path.join(ROOT, "data", f"{split}.jsonl"))}
        silver = {}
        fixes = os.path.join(ROOT, "work", "ocr_improver", "fixes.jsonl")
        for f in load_jsonl(fixes) if os.path.exists(fixes) else []:
            if f.get("kind") == "text" and (f.get("confidence") or 0) >= 0.9 and f.get("options"):
                silver[f["key"]] = f["options"]

        keys = [k for k in cand if k in cur]
        n = len(keys)
        cur_have = sum(1 for k in keys if cur[k])
        cand_have = sum(1 for k in keys if cand[k])
        s_keys = [k for k in keys if k in silver]
        s_read = [k for k in s_keys if cand[k]]
        s_match = [k for k in s_read if norm(cand[k]) == norm(silver[k])]
        s_wrong = [k for k in s_read if norm(cand[k]) != norm(silver[k])]
        lost = [k for k in keys if cur[k] and not cand[k]]
        changed = [k for k in keys if cur[k] and cand[k] and norm(cur[k]) != norm(cand[k])]

        print(f"\nProblems compared: {n}")
        print(f"(a) with options: current {cur_have}/{n} ({100 * cur_have / max(n, 1):.1f}%)  "
              f"candidate {cand_have}/{n} ({100 * cand_have / max(n, 1):.1f}%)  gain {cand_have - cur_have:+d}")
        print(f"(b) silver (validated text fixes) in this set: {len(s_keys)}; candidate reads {len(s_read)}, "
              f"exact match {len(s_match)}, disagree {len(s_wrong)} "
              f"({100 * len(s_wrong) / max(len(s_read), 1):.1f}% of those read)")
        print(f"(c) regressions: lost {len(lost)}, changed {len(changed)}")
        for label, ks, ref in (("disagree with silver", s_wrong, silver), ("changed vs current", changed, cur)):
            for k in ks[:5]:
                print(f"    {label}: {k}\n      candidate {json.dumps(cand[k], ensure_ascii=False)}\n"
                      f"      reference {json.dumps(ref[k], ensure_ascii=False)}")
        for k in lost[:5]:
            print(f"    lost: {k}  current {json.dumps(cur[k], ensure_ascii=False)}")
    finally:
        if args.keep:
            print("kept", tmp)
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
