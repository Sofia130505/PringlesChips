# Multi-agent orchestration

Fable (Claude Code) orchestrates; three DeepSeek 4.1 workers run on helmcode; Opus 5.5 validates. See `CLAUDE.md` for the roles and the pipeline.

## Setup (Windows, once)

The venv must be Python 3.11 or 3.12, because `rapidocr_onnxruntime` (used by the data prep) has no 3.13 build. If `py -0p` lists no 3.11/3.12, install one (for example `uv python install 3.11`) and create the venv with that interpreter.

```powershell
py -3.11 -m venv .venv   # Python 3.11 or 3.12: rapidocr_onnxruntime does not support 3.13
.venv\Scripts\activate
$env:PYTHONUTF8 = "1"    # Windows defaults to cp1252 and OCR text needs UTF-8 (Claude Code sets it via .claude/settings.json)
pip install -r laptop\requirements.txt
copy orchestration\.env.example orchestration\.env   # then fill in the helmcode values
python orchestration\helm.py                          # should print OK
```

Then start Claude Code in the repo folder. `.claude/settings.json` selects Fable as the main model, and `.claude/agents/validator.md` runs the validator on Opus 5.5 at medium effort. Type `/orchestrate ocr` to start.

## Files

| File | What it does |
| --- | --- |
| `helm.py` | `chat(system, user)` against helmcode, OpenAI or Anthropic format, with retries |
| `run_agent.py` | `task` (one brief, one reply, proposed files) and `batch` (one prompt over a JSONL file, in parallel, resumable) |
| `roles/*.md` | The worker prompts. `<role>.md` for task mode, `<role>.batch.md` for batch mode |
| `dump_ocr_raw.py` | Reruns OCR and saves the raw lines for problems whose options look broken |
| `apply_fixes.py` | Merges repaired options into `data/*_fixed.jsonl`, never touching the originals |
| `build_ft_dataset.py` | Chat-format SFT set from the fixed training data, same prompt as the board |

## Watching the agents

From the repo folder (`agents` is `agents.cmd`, which runs `orchestration/agents.py` with the project venv):

| Command | Shows |
| --- | --- |
| `agents status` | One row per agent: calls, ok, failed, ok %, median and p95 seconds, input/output/reasoning tokens, last activity, what it is doing now |
| `agents watch` | Live view (status, last 10 events, job progress), refreshed every 5 s until Ctrl+C. `--interval 2` to change |
| `agents jobs` | Batch progress (done/total, rate per minute, ETA) and every task job with its proposed files and validator verdict |
| `agents verdicts` | Validator ACCEPT / REJECT / NEEDS MEASUREMENT counts, with each job's reason |
| `agents ocr` | OCR improver quality: fixes by kind, confidence histogram, how many pass `apply_fixes.py`, coverage before and after per language |
| `agents tokens` | Token totals by agent, day and job, and Claude usage by model (`--since 2026-11-15`) |
| `agents tail -n 20` | Latest exchanges, one line each. `--agent ocr_improver` to filter, `--follow` to keep watching |
| `agents show <key or job>` | One exchange in full: brief or input, reasoning, reply, tokens. `agents show -1` is the latest |
| `agents errors` | Failures grouped by error message |

Add `--no-color` to any command when piping the output to a file.
