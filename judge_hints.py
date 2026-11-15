#!/usr/bin/env python3
"""Generate hints on the validation set and have a small judge model score them.

    python3 judge_hints.py --limit 60
    python3 judge_hints.py --limit 60 --judge-port 8084 --hint-port 8081

The judge sees the problem, the correct answer, and the hint, then returns
    <sound 0-2> <helpful 0-2> <reveals yes|no> <note>
forced by a grammar, so it is always parseable. Writes results/hint-judge-*.csv.

sound   2 = mathematically correct and points at a useful relation
        1 = vague but not wrong
        0 = wrong, irrelevant, or misreads the problem
helpful 2 = concrete next step, no answer revealed
        1 = generic
        0 = says nothing useful
reveals yes if the hint states or strongly implies the correct option.
"""
import argparse
import collections
import csv
import json
import os
import random
import statistics
import time
import urllib.request

from copilot.config import CONFIG
from copilot.llm import hint, hint_degenerate, hint_leaks, language_ok

JUDGE_SYSTEM = """You rate hints written for school maths students. Reply with three fields: sound helpful reveals
sound: 2 correct idea, 1 vague but true, 0 wrong or irrelevant.
helpful: 2 concrete next step, 1 generic, 0 useless.
reveals: yes if the hint gives the answer in any form (letter, digits, or words), else no.

Example A
Problem: A train covers 120 km in 2 hours. What is its average speed? A) 40 B) 50 C) 60 D) 70 E) 80
Correct answer: C) 60
Hint: The answer is C, the speed is 60 km/h.
Rating: 2 0 yes

Example B
Problem: A train covers 120 km in 2 hours. What is its average speed? A) 40 B) 50 C) 60 D) 70 E) 80
Correct answer: C) 60
Hint: Compare the distance covered with the time taken.
Rating: 2 2 no

Example C
Problem: A train covers 120 km in 2 hours. What is its average speed? A) 40 B) 50 C) 60 D) 70 E) 80
Correct answer: C) 60
Hint: Consider the ionic radius of a sodium ion.
Rating: 0 0 no

Example D
Problem: A train covers 120 km in 2 hours. What is its average speed? A) 40 B) 50 C) 60 D) 70 E) 80
Correct answer: C) 60
Hint: Look at the problem.
Rating: 1 0 no
"""

JUDGE_GRAMMAR = r'''
root ::= rating " " rating " " reveals
rating ::= "0" | "1" | "2"
reveals ::= "yes" | "no"
'''


def post(url, payload, timeout=300):
    request = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def format_options(problem):
    options = problem.get("options") or {}
    return "\n".join(f"{letter}) {options[letter]}" for letter in "ABCDE" if letter in options) or "(none read)"


def judge(problem, text, url):
    label = problem["label"]
    value = (problem.get("options") or {}).get(label, "")
    user = (f"Problem:\n{problem['text'].strip()}\n\n"
            f"Options:\n{format_options(problem)}\n\n"
            f"Correct answer: {label}) {value}\n\n"
            f"Hint to rate:\n{text}")
    response = post(url, {
        "messages": [{"role": "system", "content": JUDGE_SYSTEM},
                     {"role": "user", "content": user + "\nRating:"}],
        "max_tokens": 8,
        "temperature": 0,
        "grammar": JUDGE_GRAMMAR,
        "cache_prompt": True,
    })
    raw = (response["choices"][0]["message"].get("content") or "").strip()
    parts = raw.split()
    if len(parts) != 3:
        return {"sound": None, "helpful": None, "reveals": None}
    return {"sound": int(parts[0]), "helpful": int(parts[1]), "reveals": parts[2] == "yes"}


SOLVER_SYSTEM = ("You solve multiple-choice maths problems for school students. "
                 "Reply with the letter of the correct option.")


def solve_with(problem, url, hint_text=None):
    """One letter, no reasoning. Measures whether the hint changes the answer for the better."""
    text = problem["text"].strip()
    if hint_text:
        text += f"\n\nHint: {hint_text}"
    response = post(url, {
        "messages": [{"role": "system", "content": SOLVER_SYSTEM},
                     {"role": "user", "content": text + "\n\n" + format_options(problem) + "\nAnswer:"}],
        "grammar": "root ::= [A-E]",
        "max_tokens": 1,
        "temperature": 0,
        "cache_prompt": True,
    })
    return (response["choices"][0]["message"].get("content") or "").strip()[:1]


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--input", default="data/val.jsonl")
    p.add_argument("--limit", type=int, default=60)
    p.add_argument("--hint-port", type=int, default=CONFIG["LLM_PORT"])
    p.add_argument("--judge-port", type=int, default=8084)
    p.add_argument("--no-lift", action="store_true", help="skip the with/without-hint solver check")
    p.add_argument("--out", default="")
    args = p.parse_args()

    with open(args.input) as f:
        problems = [json.loads(line) for line in f if line.strip()]
    random.Random(42).shuffle(problems)
    # Keep both languages in the sample even when --limit is small.
    by_lang = collections.defaultdict(list)
    for problem in problems:
        by_lang[problem["language"]].append(problem)
    sample = []
    for i in range(args.limit):
        for lang in sorted(by_lang):
            if len(by_lang[lang]) > i and len(sample) < args.limit:
                sample.append(by_lang[lang][i])
    sample = sample[:args.limit]

    hint_url = f"http://127.0.0.1:{args.hint_port}/v1/chat/completions"
    judge_url = f"http://127.0.0.1:{args.judge_port}/v1/chat/completions"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_path = args.out or f"results/hint-judge-{stamp}.csv"

    rows = []
    with open(out_path, "w", newline="") as out:
        writer = csv.writer(out)
        writer.writerow(["id", "language", "level", "has_options", "label", "hint",
                         "tokens_out", "hint_seconds", "auto_leaks", "language_ok", "degenerate",
                         "sound", "helpful", "reveals",
                         "answer_without", "answer_with_hint"])
        for n, problem in enumerate(sample, 1):
            start = time.perf_counter()
            text, timings = hint(problem, url=hint_url)
            hint_seconds = round(time.perf_counter() - start, 2)
            verdict = judge(problem, text, judge_url)
            without = with_hint = ""
            if not args.no_lift:
                without = solve_with(problem, judge_url)
                with_hint = solve_with(problem, judge_url, text)
            row = {
                "id": problem["id"], "language": problem["language"], "level": problem["level"],
                "has_options": bool(problem.get("options")), "label": problem["label"], "hint": text,
                "tokens_out": timings.get("predicted_n", 0), "hint_seconds": hint_seconds,
                "auto_leaks": "|".join(hint_leaks(text, problem)),
                "language_ok": language_ok(problem, text),
                "degenerate": hint_degenerate(text),
                "sound": verdict["sound"], "helpful": verdict["helpful"],
                "reveals": verdict["reveals"],
                "answer_without": without, "answer_with_hint": with_hint,
            }
            rows.append(row)
            writer.writerow(["" if row[k] is None else row[k] for k in row])
            out.flush()
            print(f"[{n}/{len(sample)}] {row['id']:<15} {row['language']} "
                  f"sound={row['sound']} helpful={row['helpful']} reveals={row['reveals']} "
                  f"| {text[:80]}")

    scored = [r for r in rows if r["sound"] is not None]
    def pct(fn):
        return 100 * sum(1 for r in scored if fn(r)) / max(1, len(scored))

    print("\n" + "=" * 64)
    print(f"Judged hints: {len(scored)}/{len(rows)}   (judge: port {args.judge_port})")
    print(f"sound   mean {statistics.mean(r['sound'] for r in scored):.2f}/2   "
          f"correct-and-useful {pct(lambda r: r['sound'] == 2):.0f}%   "
          f"not wrong {pct(lambda r: r['sound'] >= 1):.0f}%")
    print(f"helpful mean {statistics.mean(r['helpful'] for r in scored):.2f}/2   "
          f"concrete nudge {pct(lambda r: r['helpful'] == 2):.0f}%   "
          f"not useless {pct(lambda r: r['helpful'] >= 1):.0f}%")
    print(f"reveals answer (judge) {pct(lambda r: r['reveals']):.0f}%   "
          f"auto leak {pct(lambda r: r['auto_leaks']):.0f}%")
    print(f"degenerate {pct(lambda r: r['degenerate']):.0f}%   "
          f"language wrong {pct(lambda r: r['language_ok'] is False):.0f}%")
    print(f"hint latency mean {statistics.mean(r['hint_seconds'] for r in rows):.2f} s, "
          f"tokens {statistics.mean(r['tokens_out'] for r in rows):.1f}")

    lift = [r for r in rows if r["answer_without"] and r["answer_with_hint"]]
    if lift:
        base = sum(r["answer_without"] == r["label"] for r in lift)
        hinted = sum(r["answer_with_hint"] == r["label"] for r in lift)
        helped = sum(r["answer_without"] != r["label"] and r["answer_with_hint"] == r["label"] for r in lift)
        hurt = sum(r["answer_without"] == r["label"] and r["answer_with_hint"] != r["label"] for r in lift)
        print(f"Solver accuracy without hint {base}/{len(lift)} ({100 * base / len(lift):.0f}%), "
              f"with hint {hinted}/{len(lift)} ({100 * hinted / len(lift):.0f}%)")
        print(f"  answer changed: helped {helped}, hurt {hurt}, unchanged {len(lift) - helped - hurt}")

    for title, pick in (("Worst (sound 0)", lambda r: r["sound"] == 0),
                        ("Best (sound 2, helpful 2)", lambda r: r["sound"] == 2 and r["helpful"] == 2)):
        examples = [r for r in scored if pick(r)][:5]
        if examples:
            print(f"\n{title}:")
            for r in examples:
                print(f"  [{r['id']} {r['language']}] {r['hint']}")
                print(f"      judge: sound {r['sound']}, helpful {r['helpful']}, reveals {r['reveals']}")

    print(f"\nDetails: {out_path}")


if __name__ == "__main__":
    main()
