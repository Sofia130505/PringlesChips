# Math on the Edge: an offline M3Kang copilot on the Arduino UNO Q

**What it does.** Our copilot reads a Kangaroo maths problem and answers with one letter, A to E. It runs fully offline on the Arduino UNO Q 4 GB. We got there by fixing the OCR that reads the answer options out of the problem images, then fine-tuning Qwen3.5 0.8B (LoRA) on the cleaned data and deploying it to the board as a Q8_0 GGUF.

> The original challenge README, with board setup steps 0 to 15, is kept in [README_challenge.md](README_challenge.md).

## Architecture

```
 laptop (preparation only)                       Arduino UNO Q (offline)
 ------------------------------                  ---------------------------------------------
 M3Kang (Hugging Face) -> laptop/prepare_m3kang.py   predict.py / eval.py
   RapidOCR + options parser (r0..r5)               -> copilot/pipeline.py (stdlib Python)
   -> data/train.jsonl, data/val.jsonl              -> llama-server :8081  Qwen3.5 0.8B ft-v1 Q8_0
 finetune/train_lora.py (LoRA, RTX 4060)            -> (optional) llama-server :8082 bge-small, index.db
   -> merge_lora.py -> convert_gguf.ps1 -> GGUF     -> one letter A-E, < 60 s
```

- **Linux side (QRB2210):** two llama.cpp services (commit pinned in `config.env`): the language model on port 8081 and the bge-small-en-v1.5 embedding model on 8082. `copilot/` builds the prompt and parses the letter. The final configuration runs with **retrieval off** (`--rag 0`), because the fine-tuned model was trained without retrieved examples. The ablation below shows retrieval hurts it.
- **Microcontroller:** not used in the final submission.
- **M3Kang:** used on the laptop to build the training data and the validation set. No M3Kang data is in this repository; see the [dataset card](https://huggingface.co/datasets/qualcomm/M3Kang) (Torres-Camps et al., 2026, [arXiv:2601.16218](https://arxiv.org/abs/2601.16218)).
- **How we built it (laptop):** a multi-agent loop (`orchestration/`). Claude orchestrated. DeepSeek workers (OCR improver, prediction improver, fine-tuner, evaluator) wrote the code. An Opus validator accepted or rejected every change. Every message and token count is logged (`orchestration/agents.py`, `token_report.py`).

## How to replicate it

Start from a board with steps 0 to 12 of [README_challenge.md](README_challenge.md) done.

1. **Prepare the data on the laptop** (Python 3.11; the OCR uses CUDA if available):
   ```bash
   python laptop/prepare_m3kang.py --languages eng,cat
   ```
   You should see `data/train.jsonl` and `data/val.jsonl`. Most problems now have five options A-E.
2. **Fine-tune** (see `finetune/README.md`; we used an 8 GB RTX 4060):
   ```bash
   python orchestration/build_ft_dataset.py
   python finetune/train_lora.py
   python finetune/merge_lora.py
   powershell -File finetune/convert_gguf.ps1
   ```
   Merge in float32 (bf16 flipped answers). The result is `qwen3.5-0.8b-ft-v1-Q8_0.gguf` (774.2 MB, sha256 `9b5f4694…f5f751ba2840071f7a705cd5f4ad7`).
3. **Deploy:** copy the GGUF to `~/models/` on the board and point `LLM_FILE`, `LLM_SHA256` and `LLM_ALIAS` in `config.env` at it. Then run `bash board/04_install_services.sh`. `curl -s localhost:8081/v1/models` should list `qwen3.5-0.8b-ft-v1`. Full commands: `finetune/README.md`. On Windows, `BOARD.cmd` does the copy and the check over SSH.
4. **Run:**
   ```bash
   python3 predict.py --rag 0 ...
   python3 eval.py --limit 0 --rag 0 --name ft-v1-board
   ```

## Results

**OCR: options read exactly right** (exact match against an answer key; text-only / with image):

| Round | What changed | Dev (2,406 problems) |
| --- | --- | --- |
| original | first-pass parser | 66.4 / 47.4 |
| r0 | second OCR pass on the enlarged options strip | 83.4 / 64.7 |
| r1 | assign values by position, not reading order | 86.3 / 77.9 |
| r2b | units, € and symbols from all five options | 86.9 / 82.0 |
| r3d | stacked fractions | 88.0 / 83.3 |
| r4 | clean-up of near-misses | 88.3 / 85.3 |
| r5 | rescue when nothing parses | 88.9 / 85.8 |
| **held-out test (994, never seen)** | original → final | **63.7 → 90.7 / 45.9 → 85.2** |

**Answering** (`results/ablations.csv`; laptop runs use llama.cpp with the board's flags):

| Experiment | Problems | RAG | Accuracy | Mean / worst latency |
| --- | --- | --- | --- | --- |
| Challenge baseline (board) | 40 eng | 0 | 22.5% | — |
| base Q8, laptop | 562 val | 0 | 23.3% | 0.2 / 0.8 s |
| **ft-v1 Q8, laptop** | 562 val | 0 | **29.9%** | 0.1 / 0.4 s |
| ft-v1, demo set, laptop | 100 | 0 | 25.0% | 0.1 / 0.6 s |
| ft-v1 on the board | val subset | 0 | ≈29% | median 9.5 s, worst 16.2 s |
| ft-v1 on the board | val subset | 1 | ≈20.5% | — |

Board runs used small subsets (50 to 100 problems), so treat them as rough. The laptop runs are the full 562-problem validation set.

## Error analysis

- Fine-tuning gave +6.6 points on the same 562 problems. Part of the gain comes from the model no longer collapsing onto one letter.
- English and Catalan versions of the same problem are not independent, so the effective sample is smaller than 562.
- The remaining OCR failures on dev: 96 "other", 94 units/symbols (mostly a √ or exponent the OCR never captured), 49 fractions, 48 with no options found, 14 with glued-on text. When the options are wrong, the model can't be right.
- Retrieval with one example (k=1) lowered ft-v1 from 29% to 20.5% on the board: the retrieved example distracts a model trained without one.

## What didn't work, and what's next

- **RAG with ft-v1** hurt accuracy. A model fine-tuned *with* a retrieved example (`experiments/ft_rag/`, not submitted) is being tested.
- A **bf16 merge** changed answers; float32 fixed it.
- **Batch 8** ran out of GPU memory (vocabulary of ~248k); we used 2 × 8 gradient accumulation.
- The board can't run the OCR (no rapidocr), so new problems must be prepared on a laptop.
- Next: an error analysis by topic and level, hints instead of only letters, and the LED matrix / web page from step 15.

## The team

Datathon FME 2026, Qualcomm challenge. Built with Claude Code (orchestrator and validator) and DeepSeek workers. Our code is MIT-licensed. llama.cpp, Qwen3.5, bge-small and RapidOCR keep their own licenses.
