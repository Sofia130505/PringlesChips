@echo off
rem Deploy the fine-tuned model to the Arduino UNO Q and test it on 50 problems: ONE double-click.
rem You may be asked for the board password at most twice: once to install the SSH key (first run
rem only) and once by sudo on the board. The password is never stored.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0finetune\board.ps1"
echo.
pause
