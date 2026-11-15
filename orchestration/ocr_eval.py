"""Score OCR/parsing CODE against a frozen answer key. DeepSeek improves the code; its earlier
image readings serve only as the key, never as data.

  python orchestration/ocr_eval.py cache-boxes              # once: raw OCR boxes of every problem image
  python orchestration/ocr_eval.py build-key                # once: freeze answer key + dev/test split
  python orchestration/ocr_eval.py score laptop/prepare_m3kang.py --name v1 --split dev
  python orchestration/ocr_eval.py score <candidate.py> --name r1 --split dev --compare v1

Files (work/ocr_eval/):
  boxes.jsonl        {"key", "boxes": [[box, text, score], ...]}  first-pass RapidOCR output, raw text
  answer_key.jsonl   {"key", "id", "language", "text_only", "split", "expected": {...} or {}, "source"}
                     expected {} means the options are pictures: the code is right to return {}.
  results_<name>_<split>.jsonl and summary_<name>_<split>.json

A candidate is any copy of prepare_m3kang.py. If it defines
    extract_options(image_bytes, boxes, ocr) -> dict
the scorer calls it (boxes are the cached first pass; ocr is a live RapidOCR for second passes).
Otherwise it calls parse_options(boxes). The scorer never passes labels or the key to the candidate.

Metric (the other team's): problems whose code options exactly match the key (whitespace removed,
lower case, unicode minus as "-") / all problems in the split, separately for text-only and image
problems. Problems with no trustworthy key are left out and counted.
"""
import argparse
import collections
import hashlib
import importlib.util
import json
import os
import re
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EVAL = os.path.join(ROOT, "work", "ocr_eval")
BOXES = os.path.join(EVAL, "boxes.jsonl")
KEY = os.path.join(EVAL, "answer_key.jsonl")
IMAGES = os.path.join(ROOT, "data", "images")
LETTERS = "ABCDE"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def jl(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def norm_value(v):
    v = str(v).replace("−", "-").replace("–", "-")
    # Typographic variants the answer key itself spells both ways: count them as equal.
    v = v.replace("′", "'").replace("’", "'").replace("″", '"').replace("”", '"').replace("“", '"')
    return re.sub(r"\s+", "", v).lower()


def norm(options):
    return {k: norm_value(v) for k, v in (options or {}).items()}


def valid(o):
    return (isinstance(o, dict) and sorted(o) == list(LETTERS)
            and len({norm_value(v) for v in o.values()} - {""}) == 5)


def image_path(key):
    return os.path.join(IMAGES, key.replace("|", "_") + ".png")


def load_module(path, name):
    sys.path.insert(0, os.path.dirname(os.path.abspath(path)))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- cache-boxes ------------------------------------------------------------------

def cmd_cache_boxes(args):
    prep = load_module(os.path.join(ROOT, "laptop", "prepare_m3kang.py"), "prep_v1")
    ocr = prep.make_ocr()
    keys = [r["key"] for r in jl(os.path.join(ROOT, "data", "ocr_all.jsonl"))]
    done = {r["key"] for r in jl(BOXES)}
    os.makedirs(EVAL, exist_ok=True)
    t0, n = time.time(), 0
    with open(BOXES, "a", encoding="utf-8") as out:
        for key in keys:
            if key in done:
                continue
            with open(image_path(key), "rb") as f:
                boxes, _ = ocr(f.read())
            boxes = [[[[float(x), float(y)] for x, y in box], text, float(score)] for box, text, score in (boxes or [])]
            out.write(json.dumps({"key": key, "boxes": boxes}, ensure_ascii=False) + "\n")
            out.flush()
            n += 1
            if n % 200 == 0:
                print(f"  {n} cached, {n / (time.time() - t0):.1f}/s", flush=True)
    print(f"boxes cached: {len(done) + n} in {BOXES}")


# --- build-key --------------------------------------------------------------------

def cmd_build_key(args):
    meta = {}
    for split in ("train", "val"):
        for r in jl(os.path.join(ROOT, "data", f"{split}.jsonl")):
            meta[f"{r['id']}|{r['language']}"] = r
    verify = {r["key"]: r for r in jl(os.path.join(ROOT, "work", "ocr_improver", "verify.jsonl"))}
    fixes = {r["key"]: r for r in jl(os.path.join(ROOT, "work", "ocr_improver", "fixes.jsonl"))}
    transcribe = {r["key"]: r for r in jl(os.path.join(ROOT, "work", "ocr_improver", "transcribe.jsonl"))}
    rows, why = [], collections.Counter()
    for key, m in meta.items():
        expected, source = None, None
        v, f, t = verify.get(key), fixes.get(key), transcribe.get(key)
        if v is not None:
            if v.get("verdict") == "picture":
                expected, source = {}, "verify:picture"
            elif valid(v.get("options")) and (v.get("confidence") or 0) >= 0.9:
                expected, source = v["options"], f"verify:{v.get('verdict')}"
        elif f is not None:
            if f.get("kind") == "picture":
                expected, source = {}, "repair:picture"
            elif valid(f.get("options")) and (f.get("confidence") or 0) >= 0.8:
                expected, source = f["options"], "repair:text"
        elif t is not None:
            if t.get("kind") == "picture":
                expected, source = {}, "transcribe:picture"
            elif valid(t.get("options")) and (t.get("confidence") or 0) >= 0.9:
                expected, source = t["options"], "transcribe:text"
        if expected is None:
            why["no trustworthy key"] += 1
            continue
        bucket = int(hashlib.sha256(m["id"].encode()).hexdigest(), 16) % 10
        rows.append({"key": key, "id": m["id"], "language": m["language"], "level": m["level"],
                     "text_only": m["text_only"], "split": "dev" if bucket < 7 else "test",
                     "expected": expected, "source": source})
        why[source] += 1
    os.makedirs(EVAL, exist_ok=True)
    with open(KEY, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"answer key: {len(rows)} problems -> {KEY}")
    for k, n in why.most_common():
        print(f"  {k:<22} {n}")
    for split in ("dev", "test"):
        part = [r for r in rows if r["split"] == split]
        print(f"  {split}: {len(part)} (text_only {sum(r['text_only'] for r in part)}, "
              f"image {sum(not r['text_only'] for r in part)}, picture keys {sum(1 for r in part if not r['expected'])})")


# --- score ------------------------------------------------------------------------

def category(got, exp):
    if not exp:
        return "picture: code returned options" if got else "ok"
    if not got:
        return "missing: no options"
    g, e = norm(got), norm(exp)
    if g == e:
        return "ok"
    if sorted(g.values()) == sorted(e.values()):
        return "wrong: letters swapped/shifted"
    if any("/" in x for x in e.values()) and not any("/" in x for x in g.values()):
        return "wrong: fraction"
    bad = [k for k in LETTERS if g.get(k) != e.get(k)]
    if all(e[k] in g.get(k, "") and g.get(k) != e[k] for k in bad):
        return "wrong: extra text glued on"
    if any(re.search(r"[€$%°²³×√π^]|cm|m$|kg|km|ml", e[k]) for k in bad):
        return "wrong: unit/currency/symbol"
    return "wrong: other"


class CachedOCR:
    """Wraps RapidOCR for second passes: results are memoised on disk by a hash of the input
    image, so a round that only changes parsing re-uses every crop OCR'd before."""
    path = os.path.join(EVAL, "ocr_memo.jsonl")

    def __init__(self, make_ocr):
        self.make_ocr, self.ocr, self.memo = make_ocr, None, {}
        for r in jl(self.path):
            self.memo[r["h"]] = r["boxes"]
        self.hits = self.misses = 0

    def __call__(self, image):
        import numpy as np
        raw = image if isinstance(image, (bytes, bytearray)) else np.ascontiguousarray(image).tobytes()
        shape = "" if isinstance(image, (bytes, bytearray)) else str(getattr(image, "shape", ""))
        h = hashlib.sha256(shape.encode() + raw).hexdigest()
        if h in self.memo:
            self.hits += 1
            return self.memo[h], None
        if self.ocr is None:
            self.ocr = self.make_ocr()
        boxes, _ = self.ocr(image)
        boxes = [[[[float(x), float(y)] for x, y in box], text, float(score)] for box, text, score in (boxes or [])]
        self.memo[h] = boxes
        self.misses += 1
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps({"h": h, "boxes": boxes}, ensure_ascii=False) + "\n")
        return boxes, None


def cmd_score(args):
    key = [r for r in jl(KEY) if r["split"] == args.split]
    if args.limit:
        key = key[:args.limit]
    boxes = {r["key"]: r["boxes"] for r in jl(BOXES)}
    mod = load_module(args.candidate, f"cand_{args.name}")
    has_extract = hasattr(mod, "extract_options")
    ocr = CachedOCR(mod.make_ocr) if has_extract else None
    results, t0 = [], time.time()
    for r in key:
        b = boxes.get(r["key"])
        if b is None:
            continue
        if has_extract:
            with open(image_path(r["key"]), "rb") as f:
                got = mod.extract_options(f.read(), b, ocr)
        else:
            got = mod.parse_options(b)
        cat = category(got or {}, r["expected"])
        results.append({"key": r["key"], "text_only": r["text_only"], "language": r["language"],
                        "got": got or {}, "expected": r["expected"], "category": cat})
    secs = time.time() - t0
    if ocr is not None:
        print(f"  second-pass OCR: {ocr.hits} cached, {ocr.misses} new")
    out = os.path.join(EVAL, f"results_{args.name}_{args.split}.jsonl")
    with open(out, "w", encoding="utf-8") as f:
        for x in results:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")

    def acc(rows):
        return sum(x["category"] == "ok" for x in rows), len(rows)
    groups = {"text_only": [x for x in results if x["text_only"]],
              "image": [x for x in results if not x["text_only"]],
              "eng": [x for x in results if x["language"] == "eng"],
              "cat": [x for x in results if x["language"] == "cat"], "all": results}
    summary = {g: dict(zip(("correct", "n"), acc(rows))) for g, rows in groups.items()}
    summary["categories"] = dict(collections.Counter(x["category"] for x in results).most_common())
    summary["seconds"] = round(secs, 1)
    with open(os.path.join(EVAL, f"summary_{args.name}_{args.split}.json"), "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    print(f"{args.name} on {args.split} ({len(results)} problems, {secs:.0f} s, "
          f"{'extract_options' if has_extract else 'parse_options'}):")
    for g in ("text_only", "image", "eng", "cat", "all"):
        c, n = summary[g]["correct"], summary[g]["n"]
        print(f"  {g:<10} {c:>5}/{n:<5} {100 * c / max(n, 1):5.1f}%")
    print("  failure categories:")
    for cat, n in summary["categories"].items():
        if cat != "ok":
            print(f"    {n:>5}  {cat}")
    if args.compare:
        prev = {x["key"]: x for x in jl(os.path.join(EVAL, f"results_{args.compare}_{args.split}.jsonl"))}
        fixed = [x for x in results if x["category"] == "ok" and prev.get(x["key"], {}).get("category") != "ok"]
        broke = [x for x in results if x["category"] != "ok" and prev.get(x["key"], {}).get("category") == "ok"]
        print(f"  vs {args.compare}: newly correct {len(fixed)}, newly wrong (regressions) {len(broke)}")
        for x in broke[:8]:
            print(f"    REGRESSION {x['key']}: got {json.dumps(x['got'], ensure_ascii=False)} "
                  f"expected {json.dumps(x['expected'], ensure_ascii=False)}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("cache-boxes")
    sub.add_parser("build-key")
    s = sub.add_parser("score")
    s.add_argument("candidate")
    s.add_argument("--name", required=True)
    s.add_argument("--split", default="dev", choices=("dev", "test"))
    s.add_argument("--compare")
    s.add_argument("--limit", type=int, default=0)
    args = p.parse_args()
    {"cache-boxes": cmd_cache_boxes, "build-key": cmd_build_key, "score": cmd_score}[args.cmd](args)


if __name__ == "__main__":
    main()
