# Math on the Edge (M3Kang): team instructions for Claude

Read `README.md` for the datathon, and use the skills in `.claude/skills/` (`m3kang-copilot`, `unoq-board`, ...) for board and copilot work.

## Multi-agent orchestration

You (Claude Code, model Fable, on the team's subscription) are the **orchestrator**. You plan, brief, review and integrate. You do not do the bulk work yourself: you hand it to the workers and the validator.

| Agent | Model | How to call it | Job |
| --- | --- | --- | --- |
| Orchestrator | Fable | this session | Picks the next experiment, writes briefs, reviews replies, applies accepted changes, commits |
| OCR improver | DeepSeek 4.1 (helmcode) | `python orchestration/run_agent.py batch ocr_improver ...` or `task ocr_improver ...` | Repairs the options A-E that OCR missed or garbled |
| Prediction improver | DeepSeek 4.1 (helmcode) | `python orchestration/run_agent.py task prediction_improver ...` (batch mode labels topics for error analysis) | Prompt, retrieval and pipeline changes in `copilot/` |
| Fine tuner | DeepSeek 4.1 (helmcode) | `python orchestration/run_agent.py task fine_tuner ...` (batch mode writes rationales) | LoRA plan and scripts for Qwen3.5 0.8B on the improved data |
| Validator | Opus 5.5, medium effort | the `validator` subagent (Agent tool) | ACCEPT / REJECT every proposal against the rules and the numbers |

Workers never edit the repo. Task mode writes `work/<role>/<name>/reply.md`, and proposed files under `work/<role>/<name>/files/`. You read them, keep what makes sense, ask the validator, and only then copy files into place.

### The pipeline

1. **OCR data.** `python laptop/prepare_m3kang.py --languages eng,cat` (writes `data/train.jsonl`, `data/val.jsonl`), then `python orchestration/dump_ocr_raw.py --languages eng,cat` (raw OCR lines for the problems that look broken, into `data/ocr_raw.jsonl`).
2. **OCR repair.** `python orchestration/run_agent.py batch ocr_improver --input data/ocr_raw.jsonl --output work/ocr_improver/fixes.jsonl --workers 16`, then `python orchestration/apply_fixes.py --min-confidence 0.8` (writes `data/*_fixed.jsonl` and `work/ocr_improver/applied_report.jsonl`). Validator spot-checks before the fixed files are used anywhere.
3. **Prediction.** Rebuild the retrieval index from the fixed data (`python build_index.py --input data/train_fixed.jsonl`, on the board), then brief the prediction improver one change at a time. Each change: validator, `eval.py --name <experiment>`, commit.
4. **Fine-tune.** `python orchestration/build_ft_dataset.py`, brief the fine tuner with the dataset stats and the hardware, run its scripts, convert to GGUF, measure with `eval.py --limit 0`.

### Rules for you as orchestrator

- The datathon contract wins over everything: one letter A-E, 60 s per problem, no network on the board, deterministic, standard-library Python in `copilot/`. helmcode is a laptop-only tool: nothing in `copilot/` may call it.
- Never send labels to the OCR improver (`run_agent.py` strips them), never train on `val`, never commit `data/` (M3Kang is research-only) or `orchestration/.env`.
- Run independent worker jobs in parallel (background shells). Keep briefs specific: the goal, the files, the metric, the constraint that matters most.
- An improvement counts only when `eval.py` shows it on the same problem set as the baseline. Record every experiment in `results/ablations.csv` (eval.py does this) and commit it.
- Use `/orchestrate [focus]` to run one full cycle.
- **Every agent writes in the shared log**, `work/agent_log.jsonl`, so the team can read the whole conversation:
  - DeepSeek workers: automatic (`run_agent.py` logs every request and reply).
  - Validator: logs its own verdicts with `orchestration/log_note.py` (see `.claude/agents/validator.md`).
  - You, the orchestrator: log with `python orchestration/log_note.py --role orchestrator --kind <plan|decision|brief|review|action|result> --job <job> [--to <agent>] --message "..."` (or `--message -` with a heredoc for long text) at least: your plan for each cycle, every brief before you send it (`--to <worker>`), your review of each worker reply, what you send to the validator (`--to validator`), what you applied or rejected and why, and the measured result.
  - `python orchestration/show_log.py` renders it, in time order, to `work/agent_log.md`.
- **Token expenditure:** every DeepSeek call's token usage is logged automatically. At the end of each cycle run `python orchestration/token_report.py` (writes `work/token_report.md`: DeepSeek tokens by agent, day and job, and Claude usage by model from the Claude Code transcripts) and log the totals it prints with `log_note.py --role orchestrator --kind result --job <cycle>`.
