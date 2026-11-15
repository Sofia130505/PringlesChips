"""Token expenditure of every agent, written to work/token_report.md.

  python orchestration/token_report.py                    # everything
  python orchestration/token_report.py --since 2026-11-15

Two sources:
  1. DeepSeek workers (helmcode): the `usage` that run_agent.py logs with every call in
     work/agent_log.jsonl, by agent and job.
  2. Claude agents (Fable orchestrator, Opus validator, any other Claude session working
     on this folder): Claude Code's own session transcripts, under
     %USERPROFILE%/.claude/projects/<folder name with every non-alphanumeric character as "-">/.
     Subagent transcripts (the validator) live in a subagents/ folder or are marked
     isSidechain. Streamed messages repeat, so each message id is counted once.
"""
import argparse
import glob
import json
import os
import re
from collections import defaultdict

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "work", "agent_log.jsonl")
OUT = os.path.join(ROOT, "work", "token_report.md")


def num(x):
    return int(x or 0)


def deepseek_rows(since):
    rows = []
    if not os.path.exists(LOG):
        return rows
    with open(LOG, encoding="utf-8") as f:
        for line in f:
            try:
                e = json.loads(line)
            except ValueError:
                continue  # partial line from two concurrent writers
            u = e.get("usage")
            if not u or e.get("time", "") < since:
                continue
            details = u.get("completion_tokens_details") or {}
            pdetails = u.get("prompt_tokens_details") or {}
            rows.append({
                "agent": e.get("role", "?"), "job": e.get("name") or "batch", "day": e.get("time", "")[:10],
                "input": num(u.get("prompt_tokens")), "cached": num(pdetails.get("cached_tokens")),
                "output": num(u.get("completion_tokens")), "reasoning": num(details.get("reasoning_tokens")),
                "total": num(u.get("total_tokens")) or num(u.get("prompt_tokens")) + num(u.get("completion_tokens")),
                "image": bool(e.get("image")),
            })
    return rows


def claude_project_dirs():
    """Claude Code transcript folders for this repo and the folder above it (setup sessions)."""
    base = os.path.join(os.path.expanduser("~"), ".claude", "projects")
    enc = lambda p: re.sub(r"[^A-Za-z0-9]", "-", p)  # noqa: E731
    names = {enc(ROOT), enc(os.path.dirname(ROOT))}
    return [os.path.join(base, n) for n in sorted(names) if os.path.isdir(os.path.join(base, n))]


def claude_rows(since):
    rows, seen = [], set()
    for d in claude_project_dirs():
        for path in glob.glob(os.path.join(d, "**", "*.jsonl"), recursive=True):
            subagent = "subagents" in path.replace("\\", "/").split("/")
            with open(path, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if '"usage"' not in line:
                        continue
                    try:
                        e = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    m = e.get("message") or {}
                    u = m.get("usage")
                    if e.get("type") != "assistant" or not u:
                        continue
                    key = m.get("id") or e.get("requestId") or e.get("uuid")
                    if key in seen:
                        continue
                    seen.add(key)
                    day = (e.get("timestamp") or "")[:10]
                    if day < since[:10]:
                        continue
                    side = subagent or e.get("isSidechain")
                    agent = (e.get("agentId") and f"subagent {e.get('agentId')}") if side else "main session"
                    inp = num(u.get("input_tokens"))
                    cache_w, cache_r = num(u.get("cache_creation_input_tokens")), num(u.get("cache_read_input_tokens"))
                    out = num(u.get("output_tokens"))
                    rows.append({
                        "agent": f"{m.get('model', '?')} ({'subagent' if side else 'main'})",
                        "job": os.path.basename(path)[:8] + (" " + agent if side else ""), "day": day,
                        "input": inp + cache_w + cache_r, "cached": cache_r, "cache_write": cache_w,
                        "output": out,
                        "reasoning": num((u.get("output_tokens_details") or {}).get("thinking_tokens")),
                        "total": inp + cache_w + cache_r + out,
                    })
    return rows


def table(rows, key, title, extra_cols=()):
    agg = defaultdict(lambda: defaultdict(int))
    for r in rows:
        a = agg[r[key]]
        a["calls"] += 1
        for c in ("input", "cached", "output", "reasoning", "total") + tuple(extra_cols):
            a[c] += r.get(c, 0)
    cols = ("calls", "input", "cached") + tuple(extra_cols) + ("output", "reasoning", "total")
    lines = [f"### {title}", "", "| " + key + " | " + " | ".join(cols) + " |",
             "|" + "---|" * (len(cols) + 1)]
    for k, a in sorted(agg.items(), key=lambda kv: -kv[1]["total"]):
        lines.append(f"| {k} | " + " | ".join(f"{a[c]:,}" for c in cols) + " |")
    t = {c: sum(a[c] for a in agg.values()) for c in cols}
    lines.append("| **total** | " + " | ".join(f"**{t[c]:,}**" for c in cols) + " |")
    return lines + [""], t


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--since", default="", help="ISO date, e.g. 2026-11-15")
    p.add_argument("--out", default=OUT)
    args = p.parse_args()

    ds, cl = deepseek_rows(args.since), claude_rows(args.since)
    md = ["# Token expenditure", "",
          f"Since: {args.since or 'the beginning'}. Input includes cached tokens; for Claude, input = fresh + cache write + cache read.",
          "Claude agents run on the team's subscription: there is no per-token bill, so the Claude figures are usage, not cost.",
          ""]
    md.append("## DeepSeek workers (helmcode)")
    md.append("")
    if ds:
        lines, ds_tot = table(ds, "agent", "By agent")
        md += lines
        md += table(ds, "day", "By day")[0]
        top = defaultdict(int)
        for r in ds:
            top[(r["agent"], r["job"])] += r["total"]
        md += ["### Top 10 jobs", "", "| agent | job | total tokens |", "|---|---|---|"]
        md += [f"| {a} | {j} | {t:,} |" for (a, j), t in sorted(top.items(), key=lambda kv: -kv[1])[:10]]
        md.append("")
        images = sum(r["image"] for r in ds)
        md += [f"Calls with an image attached: {images} of {len(ds)}.", ""]
    else:
        ds_tot = {}
        md += ["No DeepSeek calls with usage logged yet.", ""]
    md.append("## Claude agents (Claude Code transcripts)")
    md.append("")
    if cl:
        lines, cl_tot = table(cl, "agent", "By model", extra_cols=("cache_write",))
        md += lines
        md += table(cl, "day", "By day", extra_cols=("cache_write",))[0]
    else:
        cl_tot = {}
        md += ["No Claude Code transcripts found for this folder.", ""]
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(md))
    print(f"DeepSeek: {ds_tot.get('calls', 0)} calls, {ds_tot.get('total', 0):,} tokens "
          f"({ds_tot.get('reasoning', 0):,} reasoning). "
          f"Claude: {cl_tot.get('calls', 0)} messages, {cl_tot.get('total', 0):,} tokens "
          f"({cl_tot.get('cached', 0):,} cache reads). -> {args.out}")


if __name__ == "__main__":
    main()
