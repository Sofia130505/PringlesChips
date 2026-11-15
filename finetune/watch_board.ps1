# Live view of the jobs running on the board (index build, RAG evals), over the SSH key.
# Started by WATCH_BOARD.cmd. Ctrl+C stops watching (the jobs keep running on the board).
# -Seconds N stops after N seconds (used for testing).
param([int]$Seconds = 0)
$remote = @'
echo "=== $(date '+%H:%M:%S')  jobs running on the board:"
ps -eo pid,etime,args | grep -E 'build_index|eval.py|rag_eval|predict.py' | grep -v grep || echo '  (none right now)'
if [ -f ~/datathon-UPC-maths-qualcomm-arduino-unoq/data/index.db ]; then
  python3 -c 'import sqlite3; print("=== index.db rows so far:", sqlite3.connect("file:" + __import__("os").path.expanduser("~/datathon-UPC-maths-qualcomm-arduino-unoq/data/index.db") + "?mode=ro", uri=True).execute("select count(*) from problems").fetchone()[0])' 2>/dev/null || true
fi
echo '=== live logs (~/build_index.log, ~/rag_eval.log). Ctrl+C to stop watching; the jobs keep running.'
LIMIT=__SECONDS__
if [ "$LIMIT" -gt 0 ]; then T="timeout $LIMIT"; else T=""; fi
$T tail -c 1500 -F ~/build_index.log ~/rag_eval.log 2>/dev/null | stdbuf -oL tr '\r' '\n'
true
'@
$remote = $remote.Replace("__SECONDS__", "$Seconds").Replace("`r", "")
$b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes($remote))
& ssh -t -o BatchMode=yes -o ConnectTimeout=8 unoq "echo $b64 | base64 -d > /tmp/watch_board.sh && bash /tmp/watch_board.sh"
if ($LASTEXITCODE -eq 255) { Write-Host "Could not connect with the SSH key (is the board on? did BOARD.cmd set up the key?)" }
