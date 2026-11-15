#!/usr/bin/env bash
# Runs ON THE BOARD (uploaded to ~/models by deploy_ft_to_board.cmd, started with ssh -t).
# Switches math-llm to the fine-tuned GGUF and checks it on 50 val problems:
# accuracy, per-question latency (60 s limit) and agreement with the laptop run.
# Asks for the sudo password once (board/04_install_services.sh uses sudo).
set -euo pipefail

GGUF=qwen3.5-0.8b-ft-v1-Q8_0.gguf
SHA=9b5f4694609cb3d86e630e6067a0e906c99f5f751ba2840071f7a705cd5f4ad7
ALIAS=qwen3.5-0.8b-ft-v1
MODELS=~/models

# Find the datathon repo on the board: the usual place first, then any folder (up to 3 levels
# below ~) that holds eval.py, config.env and board/04_install_services.sh.
REPO=""
for cand in ~/datathon-UPC-maths-qualcomm-arduino-unoq; do
  [ -f "$cand/board/04_install_services.sh" ] && REPO="$cand"
done
if [ -z "$REPO" ]; then
  found=$(find ~ -maxdepth 4 -path '*/board/04_install_services.sh' 2>/dev/null | head -1)
  if [ -n "$found" ]; then
    REPO=$(dirname "$(dirname "$found")")
    [ -f "$REPO/eval.py" ] && [ -f "$REPO/config.env" ] || REPO=""
  fi
fi
if [ -z "$REPO" ]; then
  echo "Could not find the datathon repo on the board (a folder with eval.py, config.env and board/)."
  echo "Folders in $HOME:"; ls -1d ~/*/ 2>/dev/null || true
  echo "Nothing was changed. Clone it first (README step 8):"
  echo "  git clone https://github.com/mpous/datathon-UPC-maths-qualcomm-arduino-unoq ~/datathon-UPC-maths-qualcomm-arduino-unoq"
  exit 1
fi
echo "datathon repo: $REPO"

echo "== 1/5 checking the model file"
cd "$MODELS"
echo "$SHA  $GGUF" | sha256sum --check

echo "== 2/5 pointing config.env at the fine-tuned model"
cd "$REPO"
[ -f config.env.base ] || cp config.env config.env.base   # first run only: keep the base settings
sed -i "s/^LLM_FILE=.*/LLM_FILE=$GGUF/; s/^LLM_SHA256=.*/LLM_SHA256=$SHA/; s/^LLM_ALIAS=.*/LLM_ALIAS=$ALIAS/" config.env
grep '^LLM_' config.env

echo "== 3/5 restarting math-llm"
if ! sudo -n true 2>/dev/null; then
  # Ask for the password up front, on its own visible line: the "[sudo] password" prompt itself has
  # no newline, so a Windows output capture (Tee-Object) may not show it and the window looks frozen.
  echo ">>> Type the BOARD password now and press Enter (nothing shows while you type):"
  sudo -v -p ""
fi
bash board/04_install_services.sh

echo "== 4/5 waiting for the model server"
for i in $(seq 1 90); do
  if curl -s localhost:8081/health | grep -q '"ok"'; then break; fi
  sleep 2
done
curl -s localhost:8081/v1/models | grep -o '"id":"[^"]*"' || { echo "server not answering"; exit 1; }

echo "== 5/5 eval.py on 50 val problems (data/val.jsonl, same as the laptop), RAG off"
python3 eval.py --input data/val.jsonl --limit 50 --rag 0 --name ft-v1-board-50

python3 - "$MODELS/ft_laptop_answers.csv" <<'PY'
import csv, glob, os, statistics, sys
board_csv = max(glob.glob("results/eval-*-ft-v1-board-50.csv"), key=os.path.getmtime)
board = list(csv.DictReader(open(board_csv, encoding="utf-8")))
laptop = {(r["id"], r["language"]): r for r in csv.DictReader(open(sys.argv[1], encoding="utf-8"))}
print("\nPer-question latency on the BOARD (seconds), with the laptop answer for the same problem:")
print(f"{'#':>3} {'problem':<22} {'lang':<4} {'tokens':>6} {'seconds':>8}  board laptop true")
secs, same, ok = [], 0, 0
for i, r in enumerate(board, 1):
    s = float(r["seconds"]); secs.append(s)
    lap = laptop.get((r["id"], r["language"]), {}).get("answer", "?")
    same += r["answer"] == lap; ok += r["correct"] == "1"
    flag = "  OVER 60 s" if s > 60 else ""
    print(f"{i:>3} {r['id']:<22} {r['language']:<4} {r['prompt_tokens']:>6} {s:>8.1f}  {r['answer']:^5} {lap:^6} {r['label']:^4}{flag}")
print(f"\nlatency: min {min(secs):.1f} s, median {statistics.median(secs):.1f} s, max {max(secs):.1f} s, "
      f"over 60 s: {sum(s > 60 for s in secs)} of {len(secs)}")
print(f"accuracy on these {len(board)}: {ok}/{len(board)}; same answer as the laptop run: {same}/{len(board)}")
print(f"board results file: {board_csv}")
PY
echo
echo "To switch back to the base model:  cd $REPO && cp config.env.base config.env && bash board/04_install_services.sh"
