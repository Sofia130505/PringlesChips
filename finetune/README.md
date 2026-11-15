# Fine-tuning Qwen3.5 0.8B for M3Kang (LoRA → GGUF Q8_0)

Everything here runs on the laptop (`orchestration/hardware.md`: RTX 4060 Laptop, 8 GB,
driver 592.82 / CUDA 13.1, Windows 11, Python 3.11). **Nothing is trained on the board.**

> **Before the first run:** open `finetune/train_lora.py` and `finetune/merge_lora.py` and
> confirm `BASE_MODEL = "Qwen/Qwen3.5-0.8B"` on huggingface.co. It must be the *original*
> HF checkpoint that `bartowski/Qwen_Qwen3.5-0.8B-GGUF` (see `config.env`, `LLM_REVISION`)
> was converted from — **not** the GGUF. If the id differs, change it in both files; both
> scripts write `base_model_confirmed: false` into their JSON so this stays visible.
>
> M3Kang is research-only. Do not upload the data, the adapter, the merged folder or the
> GGUF to a public hub.

## Prompt contract

`train_lora.py` imports `SYSTEM` and `format_problem()` from `copilot/llm.py` and renders
them with the model's own chat template, then trains only on the letter token and the
template's end-of-turn token. The user text on the board is `format_problem(problem) +
"\nAnswer:"` with `grammar = "root ::= [A-E]"`, `max_tokens = 1`, `temperature 0`,
`seed 42`; training matches that byte for byte (the trainer asserts the system prompt and
records a SHA-256 of a fully rendered validation prompt in `val_metrics.json`).
`data/val.jsonl` is used **only** for evaluation.

## 0. Environment (once)

