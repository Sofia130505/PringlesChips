# Watch the agents from PowerShell: .\agents.ps1 status | watch | jobs | verdicts | ocr | tokens | tail | show | errors
$env:PYTHONUTF8 = "1"
& "$PSScriptRoot\.venv\Scripts\python.exe" "$PSScriptRoot\orchestration\agents.py" @args
