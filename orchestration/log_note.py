"""Append one entry to the shared agent log (work/agent_log.jsonl).

The DeepSeek workers are logged automatically by run_agent.py. The orchestrator and the
validator call this script, so every agent's words end up in the same log:

  python orchestration/log_note.py --role orchestrator --kind decision --job ocr-full-v1 \
      --message "Running the OCR improver on all 900 flagged rows: text fixes look reliable."

  python orchestration/log_note.py --role validator --kind verdict --job ocr-full-v1 \
      --message-file work/validator/2026-11-14_20-15-00_ocr-full-v1.md

Long messages: write them to a file and pass --message-file (or pipe them on stdin with
--message -). Render the log with: python orchestration/show_log.py
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_PATH = os.path.join(ROOT, "work", "agent_log.jsonl")
ROLES = ("orchestrator", "validator", "ocr_improver", "prediction_improver", "fine_tuner")
KINDS = ("plan", "decision", "brief", "review", "verdict", "action", "result", "note")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--role", required=True, choices=ROLES)
    p.add_argument("--kind", required=True, choices=KINDS)
    p.add_argument("--job", default="", help="experiment or job name, e.g. ocr-full-v1")
    p.add_argument("--to", default="", help="who the message is for, e.g. validator or team")
    p.add_argument("--message", help="the text, or '-' to read it from stdin")
    p.add_argument("--message-file")
    args = p.parse_args()

    if args.message_file:
        with open(args.message_file, encoding="utf-8") as f:
            text = f.read()
    elif args.message == "-":
        text = sys.stdin.read()
    elif args.message:
        text = args.message
    else:
        sys.exit("Give --message, --message-file, or --message - (stdin).")

    entry = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "mode": "note", "role": args.role,
             "kind": args.kind, "name": args.job, "to": args.to, "reply": text.strip()}
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"logged {args.role}/{args.kind} ({len(text)} chars) to {os.path.relpath(LOG_PATH, ROOT)}")


if __name__ == "__main__":
    main()
