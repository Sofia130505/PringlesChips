@echo off
rem Watch the agents: agents status ^| watch ^| jobs ^| verdicts ^| ocr ^| tokens ^| tail ^| show ^| errors
set PYTHONUTF8=1
"%~dp0.venv\Scripts\python.exe" "%~dp0orchestration\agents.py" %*
