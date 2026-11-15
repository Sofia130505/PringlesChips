#!/usr/bin/env python3
"""Check the level-1 hint path: leakage, length, latency. Hints are not answers, so no accuracy.

    python3 hint_check.py --limit 20
    python3 hint_check.py --limit 40 --languages eng --max-tokens 80

Writes results/hints-<stamp>.csv and prints a short summary.
"""
import argparse
import csv
import json
import random
import statistics
import time
from collections import Counter

from copilot.config import CONFIG
from copilot.llm import detect_language, hint, hint_degenerate, hint_leaks, language_ok


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", default="data/val.jsonl")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--languages", default="", help="e.g. eng,cat")
    p.add_argument("--max-tokens", type=int, default=60)
    p.add_argument("--out", default="")
    args = p.parse_args()

    with open(args.input) as f:
        problems = [json.loads(line) for line in f if line.strip()]
    languages = set(filter(None, args.languages.split(",")))
    if languages:
        problems = [x for x in problems if x["language"] in languages]
    random.Random(42).shuffle(problems)  # same sample every run, like eval.py
    problems = problems[:args.limit]

    url = f"http://127.0.0.1:{CONFIG['LLM_PORT']}/v1/chat/completions"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_path = args.out or f"results/hints-{stamp}.csv"

    rows = []
    with open(out_path, "w", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(["id", "language", "level", "has_options", "label",
                         "words", "tokens_in", "tokens_out", "seconds", "leaks",
                         "hint_language", "language_ok", "hint"])
        for n, problem in enumerate(problems, 1):
            start = time.perf_counter()
            text, timings = hint(problem, url=url, max_tokens=args.max_tokens)
            seconds = round(time.perf_counter() - start, 2)
            leaks = hint_leaks(text, problem)
            lang_ok = language_ok(problem, text)
            words = len(text.split())
            row = {
                "id": problem["id"], "language": problem["language"], "level": problem["level"],
                "has_options": bool(problem.get("options")), "label": problem["label"],
                "words": words, "tokens_in": timings.get("prompt_n", 0),
                "tokens_out": timings.get("predicted_n", 0), "seconds": seconds,
                "leaks": "|".join(leaks), "hint_language": detect_language(text),
                "language_ok": lang_ok, "hint": text,
            }
            rows.append(row)
            writer.writerow([row[k] if row[k] is not None else "" for k in
                             ("id", "language", "level", "has_options", "label", "words", "tokens_in",
                              "tokens_out", "seconds", "leaks", "hint_language", "language_ok", "hint")])
            out.flush()
            print(f"[{n}/{len(problems)}] {row['id']} {row['language']}: {row['tokens_out']} out, "
                  f"{seconds} s, leaks: {row['leaks'] or 'none'}, lang: {row['hint_language'] or '?'}"
                  f"{'' if lang_ok is not False else ' MISMATCH'}")
            print(f"    {text[:170]}")

    leaks = sum(1 for r in rows if r["leaks"])
    long_hints = sum(1 for r in rows if r["words"] > 15)
    cut_off = sum(1 for r in rows if r["tokens_out"] >= args.max_tokens)
    with_digits = sum(1 for r in rows if any(ch.isdigit() for ch in r["hint"]))
    degenerate = sum(1 for r in rows if hint_degenerate(r["hint"]))
    mismatched = sum(1 for r in rows if r["language_ok"] is False)
    unknown = sum(1 for r in rows if r["language_ok"] is None)
    print("\n" + "=" * 60)
    print(f"Hints: {len(rows)}")
    print(f"Leaks: {leaks}   over 15 words: {long_hints}   hit max_tokens: {cut_off}   "
          f"contain digits: {with_digits}   degenerate: {degenerate}")
    print(f"Language: wrong {mismatched}, unclear {unknown}, ok {len(rows) - mismatched - unknown}")
    print(f"Output tokens: mean {statistics.mean(r['tokens_out'] for r in rows):.1f}, "
          f"max {max(r['tokens_out'] for r in rows)}")
    print(f"Latency: mean {statistics.mean(r['seconds'] for r in rows):.2f} s, "
          f"max {max(r['seconds'] for r in rows):.2f} s   (M3 Pro, not the board)")
    opener_counts = Counter(r["hint"].split(" ")[0] if r["hint"] else "-" for r in rows)
    print("Openers: " + ", ".join(f"{k} {v}" for k, v in sorted(opener_counts.items())))
    print(f"Details: {out_path}")


if __name__ == "__main__":
    main()
