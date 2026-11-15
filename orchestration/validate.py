"""Record validator verdicts under the EXACT job name, so `agents jobs` always shows them.

The validator is a Claude subagent (Opus, medium effort) started by the orchestrator; this
script is the bookkeeping around it:

  python orchestration/validate.py brief  --job ft-rag-v1          # prints the logging block to put in the brief
  python orchestration/validate.py record --job ft-rag-v1 --file work/validator/ft-rag-v1.md
  python orchestration/validate.py record --job ft-rag-v1 --message "ACCEPT ..."
  python orchestration/validate.py status --job ft-rag-v1          # last verdict for that job

Rules: one job name per task, the same name as `run_agent.py task <role> --name <job>`.
A verdict starts with ACCEPT, REJECT or NEEDS MEASUREMENT. Never record a verdict the
validator did not give; orchestrator calls (kept / rejected / superseded) go to
`log_note.py --role orchestrator --kind decision --job <job>`.
"""
import argparse
import json
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "work", "agent_log.jsonl")
FIRST = ("ACCEPT", "REJECT", "NEEDS MEASUREMENT")

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def record(job, text):
    text = text.strip()
    if not text.upper().startswith(FIRST):
        sys.exit(f"A verdict must start with one of {FIRST}; got: {text[:60]!r}")
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    entry = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), "mode": "note", "role": "validator",
             "kind": "verdict", "name": job, "to": "orchestrator", "reply": text}
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(f"recorded validator verdict for {job}: {text.splitlines()[0][:80]}")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("brief", "record", "status"):
        s = sub.add_parser(name)
        s.add_argument("--job", required=True)
        if name == "record":
            s.add_argument("--file")
            s.add_argument("--message")
    a = p.parse_args()
    if a.cmd == "brief":
        print("## Logging (required)\nBefore you reply, record your full verdict under this exact job name:\n"
              f".venv/Scripts/python orchestration/validate.py record --job {a.job} --message - <<'EOF'\n"
              "<your full reply, starting with ACCEPT / REJECT / NEEDS MEASUREMENT>\nEOF")
    elif a.cmd == "record":
        if a.file:
            text = open(a.file, encoding="utf-8").read()
        elif a.message == "-":
            text = sys.stdin.read()
        elif a.message:
            text = a.message
        else:
            sys.exit("Give --file or --message (or --message - for stdin).")
        record(a.job, text)
    else:
        last = None
        if os.path.exists(LOG):
            with open(LOG, encoding="utf-8", errors="replace") as f:
                for line in f:
                    try:
                        e = json.loads(line)
                    except ValueError:
                        continue
                    if e.get("role") == "validator" and e.get("kind") == "verdict" and e.get("name") == a.job:
                        last = e
        print(f"{a.job}: " + (f"{last['time']}  {last['reply'].splitlines()[0][:100]}" if last else "no verdict yet"))


if __name__ == "__main__":
    main()
