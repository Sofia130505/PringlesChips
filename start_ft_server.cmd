@echo off
rem Start llama-server on the laptop GPU with the fine-tuned model (same flags as the board's service).
rem Double-click to run; close this window (or press Ctrl+C) to stop the server.
cd /d "%~dp0"
tools\llama.cpp\b12302\llama-server.exe -m work\fine_tuner\gguf\qwen3.5-0.8b-ft-v1-Q8_0.gguf --host 127.0.0.1 --port 8081 --threads 4 --ctx-size 4096 --parallel 1 --cache-ram 0 --ctx-checkpoints 2 --jinja --reasoning off --reasoning-budget 0 --alias qwen3.5-0.8b-ft-v1 -ngl 99
pause
