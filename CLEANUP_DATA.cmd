@echo off
rem Delete the data files from before the OCR fix and keep the new ones under the default names,
rem on the laptop and the board (data files only). Shows the list and asks you to type YES first.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0work\cleanup_data.ps1"
echo.
pause
