@echo off
rem Push branch ocr-finetune-orchestration (1 commit, checked for secrets) to the team repo
rem https://github.com/IPat0O/PringlesChipsDatathonQualcomm as a NEW branch. Never touches main.
rem Git may open a GitHub sign-in window the first time.
cd /d "%~dp0"
git remote get-url team >nul 2>&1 || git remote add team https://github.com/IPat0O/PringlesChipsDatathonQualcomm.git
git push -u team ocr-finetune-orchestration
echo.
echo If it worked, open the pull request here:
echo   https://github.com/IPat0O/PringlesChipsDatathonQualcomm/compare/main...ocr-finetune-orchestration
pause
