"""Run the DeepSeek worker agents (via helmcode) for the orchestrator.

Two modes:

  task   One job for one role: a brief plus the files it needs. The reply (a plan, a patch,
         a script) is saved as markdown, and any ```file:path blocks are saved as proposed
         files under work/<role>/<name>/files/. Nothing in the repo is changed directly:
         the orchestrator reviews, the validator measures, and only then is it applied.

      python orchestration/run_agent.py task prediction_improver --name rag-k3 \
          --brief "Propose a prompt change for problems without options" \
          --files copilot/llm.py copilot/pipeline.py results/ablations.csv

  batch  The same role prompt over every line of a JSONL file, many requests in parallel.
         Each reply must be a JSON object. Resumable: finished keys are skipped.

      python orchestration/run_agent.py batch ocr_improver \
          --input data/ocr_raw.jsonl --output work/ocr_improver/fixes.jsonl --workers 16

Roles live in orchestration/roles/<role>.md (task mode) and <role>.batch.md (batch mode).
"""
import argparse
import base64
import concurrent.futures as cf
import json
import os
import re
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from helm import chat, last_reasoning, last_usage  # noqa: E402

ROLES = ("ocr_improver", "prediction_improver", "fine_tuner")
# The OCR improver must never see the answer, or it would "repair" options to fit it.
FORBIDDEN_FIELDS = {"ocr_improver": {"label"}}

# Every request and reply is appended here, so the team can read what the agents said
# to each other. Render it as markdown with: python orchestration/show_log.py
LOG_PATH = os.path.join(ROOT, "work", "agent_log.jsonl")
_log_lock = threading.Lock()


def log_exchange(**entry):
    entry = {"time": time.strftime("%Y-%m-%d %H:%M:%S"), **entry}
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with _log_lock, open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def role_prompt(role, batch=False):
    path = os.path.join(HERE, "roles", f"{role}{'.batch' if batch else ''}.md")
    if not os.path.exists(path):
        raise SystemExit(f"Missing role prompt: {path}")
    with open(path, encoding="utf-8") as f:
        return f.read()


def read_file(path, max_chars):
    full = os.path.join(ROOT, path)
    with open(full, encoding="utf-8", errors="replace") as f:
        text = f.read()
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n... [cut at {max_chars} characters]"
    return f"=== {path} ===\n{text}\n"


def run_task(args):
    out_dir = os.path.join(ROOT, "work", args.role, args.name)
    os.makedirs(out_dir, exist_ok=True)
    brief = args.brief
    if args.brief_file:
        with open(args.brief_file, encoding="utf-8") as f:
            brief = f.read()
    context = "".join(read_file(p, args.max_chars) for p in args.files)
    user = f"# Task from the orchestrator\n{brief}\n\n# Files\n{context or '(none)'}"
    t0 = time.time()
    with open(os.path.join(out_dir, "brief.md"), "w", encoding="utf-8") as f:
        f.write(f"# Brief to {args.role} ({args.name})\n\n{brief}\n\n"
                f"Attached files: {', '.join(args.files) or '(none)'}\n")
    try:
        reply = chat(role_prompt(args.role), user, max_tokens=args.max_tokens, temperature=args.temperature,
                     stream=True)  # long replies: a stream avoids helmcode's HTTP 408
    except Exception as e:  # log failures too, with whatever reasoning and usage came back
        log_exchange(mode="task", role=args.role, name=args.name, brief=brief, files=args.files, reply=None,
                     reasoning=last_reasoning(), usage=last_usage(), ok=False, error=str(e)[:300],
                     seconds=round(time.time() - t0, 1))
        raise
    with open(os.path.join(out_dir, "reply.md"), "w", encoding="utf-8") as f:
        f.write(reply)
    log_exchange(mode="task", role=args.role, name=args.name, brief=brief, files=args.files,
                 reply=reply, reasoning=last_reasoning(), usage=last_usage(), seconds=round(time.time() - t0, 1))
    saved = []
    for path, body in re.findall(r"```file:([^\n`]+)\n(.*?)```", reply, flags=re.S):
        path = path.strip().replace("\\", "/").lstrip("/")
        if ".." in path.split("/"):
            continue
        target = os.path.join(out_dir, "files", path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(body)
        saved.append(path)
    print(json.dumps({"role": args.role, "name": args.name, "seconds": round(time.time() - t0, 1),
                      "reply": os.path.relpath(os.path.join(out_dir, "reply.md"), ROOT),
                      "proposed_files": saved}, indent=2))


def parse_json(text):
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    if m:
        text = m.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    return json.loads(text)


def run_batch(args):
    system = role_prompt(args.role, batch=True)
    if args.prompt_file:  # a variant prompt for the same role, e.g. roles/ocr_verify.batch.md
        with open(args.prompt_file, encoding="utf-8") as f:
            system = f.read()
    with open(args.input, encoding="utf-8") as f:
        items = [json.loads(line) for line in f if line.strip()]
    key_of = lambda it: it.get("key") or f"{it['id']}|{it.get('language', '')}"  # noqa: E731
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    done = set()
    if os.path.exists(args.output):
        with open(args.output, encoding="utf-8") as f:
            done = {json.loads(line)["key"] for line in f if line.strip()}
    todo = [it for it in items if key_of(it) not in done]
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(items)} items, {len(done)} done already, running {len(todo)} with {args.workers} workers")

    lock = threading.Lock()
    out = open(args.output, "a", encoding="utf-8")
    stats = {"ok": 0, "error": 0}

    def work(item):
        hidden = FORBIDDEN_FIELDS.get(args.role, set())
        visible = {k: v for k, v in item.items() if k not in hidden and k != "image_path"}
        user = json.dumps(visible, ensure_ascii=False)
        image_b64 = None
        if item.get("image_path") and not args.no_images:
            path = os.path.join(ROOT, item["image_path"])
            if os.path.exists(path):
                with open(path, "rb") as f:
                    image_b64 = base64.b64encode(f.read()).decode()
        image = item.get("image_path") if image_b64 else None
        for attempt in range(2):
            t0, reply = time.time(), None
            try:
                reply = chat(system, user, max_tokens=args.max_tokens,
                             temperature=args.temperature, image_b64=image_b64)
                result = parse_json(reply)
                log_exchange(mode="batch", role=args.role, key=key_of(item), request=user, image=image,
                             reply=reply, reasoning=last_reasoning(), usage=last_usage(), ok=True, seconds=round(time.time() - t0, 1))
                return {"key": key_of(item), "ok": True, **result}
            except (ValueError, json.JSONDecodeError):
                log_exchange(mode="batch", role=args.role, key=key_of(item), request=user, image=image,
                             reply=reply, reasoning=last_reasoning(), usage=last_usage(), ok=False, error="reply was not JSON", seconds=round(time.time() - t0, 1))
                continue
            except Exception as e:  # noqa: BLE001  keep the batch running
                log_exchange(mode="batch", role=args.role, key=key_of(item), request=user, image=image,
                             reply=reply, reasoning=last_reasoning(), usage=last_usage(), ok=False, error=str(e)[:300], seconds=round(time.time() - t0, 1))
                return {"key": key_of(item), "ok": False, "error": str(e)[:300]}
        return {"key": key_of(item), "ok": False, "error": "reply was not JSON"}

    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        for i, row in enumerate(pool.map(work, todo), 1):
            with lock:
                if row["ok"]:
                    out.write(json.dumps(row, ensure_ascii=False) + "\n")
                    out.flush()
                stats["ok" if row["ok"] else "error"] += 1
            if i % 25 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)}  ok={stats['ok']} errors={stats['error']}", flush=True)
    out.close()
    print(f"Wrote {args.output}. Failed items are not saved, so rerun the same command to retry them.")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="mode", required=True)
    t = sub.add_parser("task")
    t.add_argument("role", choices=ROLES)
    t.add_argument("--name", required=True, help="short name for this job, e.g. ocr-fractions-v1")
    t.add_argument("--brief", default="")
    t.add_argument("--brief-file")
    t.add_argument("--files", nargs="*", default=[], help="repo-relative files to attach")
    t.add_argument("--max-chars", type=int, default=40000)
    t.add_argument("--max-tokens", type=int, default=32768)
    t.add_argument("--temperature", type=float, default=0.3)
    b = sub.add_parser("batch")
    b.add_argument("role", choices=ROLES)
    b.add_argument("--input", required=True)
    b.add_argument("--output", required=True)
    b.add_argument("--workers", type=int, default=16)
    b.add_argument("--limit", type=int, default=0)
    b.add_argument("--max-tokens", type=int, default=8192)
    b.add_argument("--temperature", type=float, default=0.0)
    b.add_argument("--no-images", action="store_true", help="ignore image_path, send text only")
    b.add_argument("--prompt-file", help="system prompt to use instead of roles/<role>.batch.md")
    args = p.parse_args()
    run_task(args) if args.mode == "task" else run_batch(args)


if __name__ == "__main__":
    main()
