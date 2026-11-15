@echo off
rem Watch the board's background jobs live (index build, RAG evals) over the SSH key: no password.
rem Ctrl+C stops watching; the jobs keep running on the board. For the DeepSeek agents use: agents watch
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0finetune\watch_board.ps1"
echo.
pause
