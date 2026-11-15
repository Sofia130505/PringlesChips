"""Watch how the agents are doing, from the terminal. Reads work/agent_log.jsonl and work/ outputs.

From the repo folder (agents.cmd runs this file with the project venv):

  agents status                     one table: every agent, calls, ok/failed, latency, tokens, what it is doing now
  agents watch [--interval 5]       live view: status, the last 10 events and job progress, until Ctrl+C
  agents jobs                       batch progress (done/total, rate, ETA) and task jobs with their verdicts
  agents verdicts                   validator ACCEPT / REJECT / NEEDS MEASUREMENT, with the reason
  agents ocr                        OCR improver quality: kinds, confidence histogram, what apply_fixes accepts, coverage
  agents tokens [--since DATE]      token totals (runs token_report.py, writes work/token_report.md)
  agents tail [-n 20] [--agent X] [--follow]    latest exchanges, one line each
  agents show <key|job|#>           one exchange in full: brief or input, reasoning, reply, tokens (-1 = latest)
  agents errors [-n 20]             failures grouped by error message

Filters: --agent ocr_improver (alias --role), --since 2026-11-14. Add --no-color to any command.
Standard library only.
"""
import argparse
import collections
import json
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join(ROOT, "work", "agent_log.jsonl")
ORDER = ("orchestrator", "ocr_improver", "prediction_improver", "fine_tuner", "evaluator", "validator")
BATCHES = {  # batch output -> its input
    os.path.join(ROOT, "work", "ocr_improver", "fixes.jsonl"): os.path.join(ROOT, "data", "ocr_raw.jsonl"),
}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if os.name == "nt":
    os.system("")  # turns on ANSI colours in the Windows console
COLOR = "--no-color" not in sys.argv and sys.stdout.isatty()
if "--no-color" in sys.argv:
    sys.argv.remove("--no-color")


def c(text, code):
    return f"\033[{code}m{text}\033[0m" if COLOR else str(text)


def pct(values, q):
    if not values:
        return None
    v = sorted(values)
    return v[min(len(v) - 1, int(round(q * (len(v) - 1))))]


def count_lines(path):
    if not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def load(args=None):
    if not os.path.exists(LOG):
        return []
    rows = []
    with open(LOG, encoding="utf-8-sig", errors="replace") as f:
        for line in f:
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue  # a line two processes wrote at the same moment: skip it
    if args is not None:
        if getattr(args, "role", None):
            rows = [e for e in rows if e.get("role") == args.role]
        if getattr(args, "since", None):
            rows = [e for e in rows if e.get("time", "") >= args.since]
    return rows


def usage(e):
    u = e.get("usage") or {}
    inp, out = int(u.get("prompt_tokens") or 0), int(u.get("completion_tokens") or 0)
    reason = int((u.get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
    return inp, out, reason


def one_line(e, width=120):
    who = e.get("role", "?")
    what = e.get("name") or e.get("key") or ""
    kind = e.get("kind") if e.get("mode") == "note" else e.get("mode", "")
    mark = "  " if e.get("ok", True) else c("x ", 31)
    secs = f"{e['seconds']:>5}s" if e.get("seconds") else "      "
    inp, out, _ = usage(e)
    tok = f"{inp + out:>6} tok" if inp + out else "          "
    text = (e.get("error") if not e.get("ok", True) else e.get("reply")) or ""
    text = " ".join(text.split())
    head = f"{e.get('time', '')[11:19]} {mark}{who:<19} {kind:<8} {what[:24]:<24} {secs} {tok}  "
    return head + text[:max(10, width - len(head))]


# --- status / watch ----------------------------------------------------------

def status_lines(args):
    agg = collections.defaultdict(lambda: {"n": 0, "ok": 0, "fail": 0, "secs": [], "in": 0, "out": 0,
                                          "reason": 0, "last": None})
    for e in load(args):
        a = agg[e.get("role", "?")]
        a["n"] += 1
        a["ok" if e.get("ok", True) else "fail"] += 1
        if e.get("seconds"):
            a["secs"].append(e["seconds"])
        inp, out, reason = usage(e)
        a["in"] += inp
        a["out"] += out
        a["reason"] += reason
        if not a["last"] or e.get("time", "") >= a["last"].get("time", ""):
            a["last"] = e
    head = (f"{'agent':<20}{'calls':>7}{'ok':>7}{'failed':>7}{'ok %':>7}{'med s':>7}{'p95 s':>7}"
            f"{'in tok':>11}{'out tok':>10}{'reason':>10}  {'last':<9}doing now")
    lines = [c(head, 1)]
    for role in sorted(set(agg) | set(ORDER), key=lambda r: ORDER.index(r) if r in ORDER else 99):
        a = agg.get(role)
        if not a:
            lines.append(c(f"{role:<20}{'-':>7}   (no entries yet)", 2))
            continue
        okp = 100 * a["ok"] / a["n"]
        med, p95 = pct(a["secs"], 0.5), pct(a["secs"], 0.95)
        last = a["last"]
        doing = f"{last.get('kind') or last.get('mode', '')} {last.get('name') or last.get('key') or ''}".strip()
        okcol = 32 if okp >= 95 else 33 if okp >= 80 else 31
        lines.append(f"{role:<20}{a['n']:>7}{a['ok']:>7}{a['fail']:>7}" + c(f"{okp:>6.0f}%", okcol)
                     + f"{(f'{med:.1f}' if med else '-'):>7}{(f'{p95:.1f}' if p95 else '-'):>7}"
                     + f"{a['in']:>11,}{a['out']:>10,}{a['reason']:>10,}  {last.get('time', '')[11:19]:<9}{doing[:40]}")
    return lines


def cmd_status(args):
    print("\n".join(status_lines(args)))


def cmd_watch(args):
    try:
        while True:
            out = [c(f"Agents  {time.strftime('%H:%M:%S')}  (refresh {args.interval:g}s, Ctrl+C to stop)", 1), ""]
            out += status_lines(args) + ["", c("Last 10 events", 1)]
            out += [one_line(e) for e in load(args)[-10:]]
            out += ["", c("Jobs", 1)] + jobs_lines()
            print("\033[2J\033[H" + "\n".join(out), flush=True)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass


# --- jobs / verdicts ---------------------------------------------------------

def jobs_lines():
    lines, log = [], load()
    five_min_ago = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 300))
    for out_path, in_path in BATCHES.items():
        if not os.path.exists(out_path):
            continue
        done, total = count_lines(out_path), count_lines(in_path)
        role = os.path.basename(os.path.dirname(out_path))
        calls = [e for e in log if e.get("role") == role and e.get("mode") == "batch"]
        recent_ok = [e for e in calls if e.get("time", "") >= five_min_ago and e.get("ok", True)]
        errors = sum(1 for e in calls if not e.get("ok", True))
        rate = len(recent_ok) / 5
        eta = f", ETA {(total - done) / rate:.0f} min" if rate and done < total else ""
        state = c("running", 33) if recent_ok else (c("done", 32) if done >= total else c("idle", 2))
        lines.append(f"batch {role:<20} {done}/{total} saved ({100 * done / max(total, 1):.0f}%), "
                     f"{errors} failed calls logged, {rate:.0f}/min{eta}  [{state}]")
    verdicts = {}
    for e in log:
        if e.get("role") == "validator" and e.get("kind") == "verdict":
            verdicts[e.get("name")] = e
    for role in ("ocr_improver", "prediction_improver", "fine_tuner"):
        base = os.path.join(ROOT, "work", role)
        if not os.path.isdir(base):
            continue
        for name in sorted(os.listdir(base)):
            d = os.path.join(base, name)
            if not os.path.isfile(os.path.join(d, "reply.md")):
                continue
            files_dir = os.path.join(d, "files")
            proposed = []
            if os.path.isdir(files_dir):
                for r, _, fs in os.walk(files_dir):
                    proposed += [os.path.relpath(os.path.join(r, f), files_dir).replace("\\", "/") for f in fs]
            when = time.strftime("%m-%d %H:%M", time.localtime(os.path.getmtime(os.path.join(d, "reply.md"))))
            v = verdicts.get(name)
            verdict = ((v.get("reply") or "?").split() or ["?"])[0] if v else "not validated"
            vcol = 32 if verdict.startswith("ACCEPT") else 31 if verdict.startswith("REJECT") else 33
            lines.append(f"task  {role:<20} {name:<22} {when}  files: {', '.join(proposed) or '-'}  verdict: "
                         + c(verdict, vcol))
    return lines or ["No jobs yet."]


def cmd_jobs(args):
    print("\n".join(jobs_lines()))


def cmd_verdicts(args):
    vs = [e for e in load() if e.get("role") == "validator" and e.get("kind") in ("verdict", "review")]
    if not vs:
        print("No validator entries yet.")
        return
    first = lambda e: ((e.get("reply") or "?").split() or ["?"])[0].strip(":.,")  # noqa: E731
    print("  ".join(f"{k}: {n}" for k, n in collections.Counter(first(e) for e in vs).most_common()))
    for e in vs:
        text = " ".join((e.get("reply") or "").split())
        f = first(e)
        col = 32 if f.startswith("ACCEPT") else 31 if f.startswith("REJECT") else 33
        print(f"{e.get('time', '')}  {e.get('name', ''):<20} " + c(f"{f:<18}", col) + text[len(f):][:90])


# --- tail / show / errors ----------------------------------------------------

def cmd_tail(args):
    for e in load(args)[-args.n:]:
        print(one_line(e))
    if not args.follow:
        return
    seen = len(load())
    try:
        while True:
            time.sleep(2)
            rows = load()
            for e in rows[seen:]:
                if not args.role or e.get("role") == args.role:
                    print(one_line(e), flush=True)
            seen = len(rows)
    except KeyboardInterrupt:
        pass


def cmd_show(args):
    rows = load()
    if args.what.lstrip("-").isdigit():
        picked = [rows[int(args.what)]] if rows else []
    else:
        picked = [e for e in rows if args.what in (e.get("key"), e.get("name"))]
    if not picked:
        sys.exit(f"Nothing in the log matches {args.what!r}. Try: agents tail")
    for e in picked[-args.n:]:
        print(c("=" * 100, 2))
        print(one_line(e, width=100))
        if e.get("brief"):
            print(c("\n--- brief ---", 1) + "\n" + e["brief"])
        if e.get("request"):
            print(c("\n--- input" + (f" (+ image {e['image']})" if e.get("image") else "") + " ---", 1) + "\n" + e["request"])
        if e.get("reasoning"):
            print(c("\n--- reasoning ---", 1) + "\n" + e["reasoning"])
        print(c("\n--- reply ---", 1) + "\n" + (e.get("reply") or e.get("error") or "(none)"))
        if e.get("usage"):
            print(c("\n--- usage ---", 1) + "\n" + json.dumps(e["usage"]))


def cmd_errors(args):
    rows = [e for e in load(args) if not e.get("ok", True)]
    if not rows:
        print("No failures logged.")
        return
    groups = collections.Counter(" ".join((e.get("error") or "?").split())[:90] for e in rows)
    print(f"{len(rows)} failed calls. Most common errors:")
    for msg, n in groups.most_common(8):
        print(f"  {n:>5}  {msg}")
    print(c("\nLatest:", 1))
    for e in rows[-args.n:]:
        print(one_line(e))


# --- ocr / tokens ------------------------------------------------------------

def valid(o):
    return (isinstance(o, dict) and sorted(o) == list("ABCDE")
            and len({str(v).strip() for v in o.values()} - {""}) == 5)


def cmd_ocr(args):
    raw = os.path.join(ROOT, "data", "ocr_raw.jsonl")
    fix_path = os.path.join(ROOT, "work", "ocr_improver", "fixes.jsonl")
    total = count_lines(raw)
    fixes = []
    if os.path.exists(fix_path):
        with open(fix_path, encoding="utf-8") as f:
            fixes = [json.loads(line) for line in f if line.strip()]
    print(f"Progress: {len(fixes)}/{total} flagged problems have a saved fix ({100 * len(fixes) / max(total, 1):.0f}%)")
    if fixes:
        kinds = collections.Counter("empty" if not f.get("options") else f.get("kind", "text") for f in fixes)
        print("By kind: " + ", ".join(f"{k} {n}" for k, n in kinds.most_common()))
        names = ["<0.5", "0.5-0.6", "0.6-0.7", "0.7-0.8", "0.8-0.9", "0.9-1.0"]
        bins = collections.Counter()
        for f in fixes:
            conf = f.get("confidence") or 0
            bins[names[0] if conf < 0.5 else names[min(5, int(conf * 10) - 4)]] += 1
        print("Confidence histogram:")
        for b in names:
            print(f"  {b:>8} {bins[b]:>5} " + c("#" * int(40 * bins[b] / len(fixes)), 36))
        text_ok = sum(1 for f in fixes if f.get("kind") != "picture" and (f.get("confidence") or 0) >= 0.8 and valid(f.get("options")))
        pic_ok = sum(1 for f in fixes if f.get("kind") == "picture" and (f.get("confidence") or 0) >= 0.9 and valid(f.get("options")))
        print(f"Pass apply_fixes thresholds: {text_ok} text (>= 0.8) + {pic_ok} picture (>= 0.9) = " + c(text_ok + pic_ok, 32))
    print("Options coverage, train + val:")
    for lang in ("eng", "cat"):
        cov = {}
        for suffix in ("", "_fixed"):
            have = tot = 0
            for split in ("train", "val"):
                path = os.path.join(ROOT, "data", f"{split}{suffix}.jsonl")
                if os.path.exists(path):
                    with open(path, encoding="utf-8") as f:
                        for line in f:
                            r = json.loads(line)
                            if r["language"] == lang:
                                tot += 1
                                have += bool(r.get("options"))
            cov[suffix] = (have, tot)
        (b, bt), (a, at) = cov[""], cov["_fixed"]
        if bt:
            after = f"{a}/{at} ({100 * a / at:.0f}%)" if at else "(run apply_fixes.py)"
            print(f"  {lang}: before {b}/{bt} ({100 * b / bt:.0f}%)   after {after}")


def cmd_tokens(args):
    cmd = [sys.executable, os.path.join(ROOT, "orchestration", "token_report.py")]
    subprocess.run(cmd + (["--since", args.since] if args.since else []), check=False)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")
    for name in ("status", "watch", "tail", "errors", "tokens"):
        s = sub.add_parser(name)
        s.add_argument("--agent", "--role", dest="role")
        s.add_argument("--since")
        if name in ("tail", "errors"):
            s.add_argument("-n", type=int, default=20)
        if name == "tail":
            s.add_argument("--follow", "-f", action="store_true")
        if name == "watch":
            s.add_argument("--interval", type=float, default=5)
    sub.add_parser("jobs")
    sub.add_parser("verdicts")
    sub.add_parser("ocr")
    s = sub.add_parser("show")
    s.add_argument("what", help="a problem key, a job name, or an entry number (-1 = latest)")
    s.add_argument("-n", type=int, default=1, help="how many matching entries to show")
    args = p.parse_args(sys.argv[1:] or ["status"])  # plain "agents" shows the status table
    {"status": cmd_status, "watch": cmd_watch, "jobs": cmd_jobs, "verdicts": cmd_verdicts, "tail": cmd_tail,
     "show": cmd_show, "errors": cmd_errors, "ocr": cmd_ocr, "tokens": cmd_tokens}[args.cmd](args)


if __name__ == "__main__":
    main()
