"""Render the agent conversation log as readable markdown.

    python orchestration/show_log.py                 # everything -> work/agent_log.md
    python orchestration/show_log.py --role ocr_improver --last 20
    python orchestration/show_log.py --key "lvl-0_2015_16|eng"

Source: work/agent_log.jsonl, in time order. The DeepSeek workers are logged by
run_agent.py; the orchestrator (Fable) and the validator (Opus) write their plans,
briefs, reviews and verdicts with orchestration/log_note.py.
"""
import argparse
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--role")
    p.add_argument("--key")
    p.add_argument("--last", type=int, default=0)
    p.add_argument("--out", default=os.path.join(ROOT, "work", "agent_log.md"))
    args = p.parse_args()

    entries = []
    log = os.path.join(ROOT, "work", "agent_log.jsonl")
    if os.path.exists(log):
        with open(log, encoding="utf-8", errors="replace") as f:
            for line in f:
                try:
                    entries.append(json.loads(line))
                except ValueError:
                    continue  # partial line from two concurrent writers
    if args.role:
        entries = [e for e in entries if e.get("role") == args.role]
    if args.key:
        entries = [e for e in entries if e.get("key") == args.key]
    entries.sort(key=lambda e: e.get("time", ""))
    if args.last:
        entries = entries[-args.last:]

    out = ["# Agent conversation log", ""]
    for e in entries:
        who = e.get("role", "?")
        what = e.get("name") or e.get("key") or ""
        status = "" if e.get("ok", True) else f"  **FAILED: {e.get('error', '')}**"
        mode = e.get("kind") if e.get("mode") == "note" else e.get("mode", "")
        to = f" → {e['to']}" if e.get("to") else ""
        out.append(f"## {e.get('time', '')} · {who}{to} · {mode} · {what}{status}")
        if e.get("mode") == "task":
            out += ["", "**Orchestrator → worker (brief):**", "", e.get("brief", ""),
                    "", f"Files: {', '.join(e.get('files', [])) or '(none)'}"]
        elif e.get("mode") == "batch":
            img = f" + image `{e['image']}`" if e.get("image") else ""
            out += ["", f"**Input{img}:**", "", "```json", e.get("request", ""), "```"]
        label = f"{who.replace('_', ' ').capitalize()} ({e.get('kind')})" if e.get("mode") == "note" else "Worker reply"
        if e.get("reasoning"):
            out += ["", "<details><summary>Worker reasoning</summary>", "", e["reasoning"], "", "</details>"]
        u = e.get("usage") or {}
        tokens = ""
        if u:
            reasoning = (u.get("completion_tokens_details") or {}).get("reasoning_tokens")
            tokens = (f" · tokens: {u.get('prompt_tokens', 0):,} in, {u.get('completion_tokens', 0):,} out"
                      + (f" ({reasoning:,} reasoning)" if reasoning else ""))
        timing = f"_{e['seconds']} s{tokens}_" if e.get("seconds") else (f"_{tokens.strip(' ·')}_" if tokens else "")
        out += ["", f"**{label}:**", "", e.get("reply") or "(no reply)", "", timing, "---", ""]
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"{len(entries)} exchanges -> {args.out}")


if __name__ == "__main__":
    main()
