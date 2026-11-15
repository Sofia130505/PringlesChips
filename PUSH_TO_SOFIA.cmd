@echo off
rem Push branch "ocr-finetune-orchestration" (commits ddc3d06 + 17ee64b) to
rem https://github.com/Sofia130505/PringlesChips as a NEW branch. No pull request (the branch
rem has a different history from Sofia's main). Never touches main, never forces.
cd /d "%~dp0"
git remote get-url sofia >nul 2>&1 || git remote add sofia https://github.com/Sofia130505/PringlesChips.git

echo === Pushing branch ocr-finetune-orchestration
git push -u sofia ocr-finetune-orchestration
if errorlevel 1 (
  echo.
  echo Push failed. If it says 403 / permission denied:
  echo   Sofia130505 must add your GitHub account as a collaborator
  echo   ^(github.com/Sofia130505/PringlesChips ^> Settings ^> Collaborators^), then run this again.
  pause
  exit /b 1
)

echo.
echo Done. The branch is here:
echo   https://github.com/Sofia130505/PringlesChips/tree/ocr-finetune-orchestration
pause
