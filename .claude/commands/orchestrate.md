---
description: Run one improvement cycle of the multi-agent pipeline (OCR, prediction, fine-tune, validate)
argument-hint: [focus, e.g. "ocr" or "prediction" or "finetune" or "all"]
---

Run one orchestration cycle as described in CLAUDE.md, section "Multi-agent orchestration". Focus: $ARGUMENTS (default: all).

1. Read `results/ablations.csv` and the latest `work/` outputs to see where we are.
2. Pick the single highest-value next job for each worker you dispatch, write a precise brief, and launch the workers with `python orchestration/run_agent.py ...`. Launch independent jobs in parallel (background shells).
3. Review each worker's reply yourself. Discard anything that breaks the rules before the validator sees it.
4. Send each surviving proposal to the `validator` subagent. Apply only what it returns as ACCEPT. Apply proposed files from `work/<role>/<name>/files/` to the repo yourself.
5. Commit each accepted change on its own, with the experiment name in the message. Never commit `data/` or `orchestration/.env`.
6. Log every step with `python orchestration/log_note.py --role orchestrator ...` as CLAUDE.md describes (plan, briefs, reviews, what goes to the validator, what you applied), check the validator logged its verdict, then run `python orchestration/show_log.py` so `work/agent_log.md` shows the whole cycle.
7. Run `python orchestration/token_report.py` and log the totals line it prints as an orchestrator `result` note.
8. End with a table: job, worker, validator verdict, accuracy before and after, next step.
