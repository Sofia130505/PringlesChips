#Requires -Version 5.1
<#
.SYNOPSIS
    Convert the merged HF model to GGUF Q8_0 with llama.cpp's converter at the commit pinned
    in config.env (LLAMA_CPP_REF), then print the size, sha256 and the config.env lines.

.DESCRIPTION
    Changes from the fine tuner's first draft (orchestrator review):
    - The converter's Python requirements go into their OWN venv (.venv-convert), so they can
      never replace the CUDA build of torch in the project .venv.
    - No cmake / llama-quantize build (that needs Visual Studio C++ tools): convert_hf_to_gguf.py
      writes Q8_0 directly with --outtype q8_0.
    - Only the converter is needed, so llama.cpp is fetched shallowly at the pinned commit
      into work\llama.cpp (not your home folder).

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File finetune\convert_gguf.ps1 -MergedDir work\fine_tuner\merged_ft-v1 -Version ft-v1
#>
param(
    [string]$MergedDir = "work\fine_tuner\merged_ft-v1",
    [string]$Version   = "ft-v1",
    [string]$OutDir    = "work\fine_tuner\gguf"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

$cfg = @{}
foreach ($line in Get-Content "config.env") {
    if ($line -match '^\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$') { $cfg[$Matches[1]] = $Matches[2].Trim('"') }
}
$Ref = $cfg["LLAMA_CPP_REF"]; $Repo = $cfg["LLAMA_CPP_REPO"]
if (-not $Ref) { throw "LLAMA_CPP_REF missing from config.env" }

# 1. llama.cpp at the pinned commit (shallow, converter only)
$Llama = Join-Path $Root "work\llama.cpp"
if (-not (Test-Path "$Llama\.git")) {
    New-Item -ItemType Directory -Force $Llama | Out-Null
    git -C $Llama init -q
    git -C $Llama remote add origin $Repo
}
git -C $Llama fetch -q --depth 1 origin $Ref
git -C $Llama checkout -q FETCH_HEAD
$Head = (git -C $Llama rev-parse HEAD).Trim()
if ($Head -ne $Ref) { throw "llama.cpp is at $Head, expected $Ref" }
Write-Host "llama.cpp at pinned commit $Ref"

# 2. The converter's own venv, kept apart from the training venv
$Py = Join-Path $Root ".venv\Scripts\python.exe"
$ConvVenv = Join-Path $Root ".venv-convert"
if (-not (Test-Path "$ConvVenv\Scripts\python.exe")) {
    $base = & $Py -c "import sys; print(sys.base_prefix)"
    & (Join-Path $base "python.exe") -m venv $ConvVenv
    & "$ConvVenv\Scripts\python.exe" -m pip install -q -r "$Llama\requirements\requirements-convert_hf_to_gguf.txt"
    if ($LASTEXITCODE -ne 0) { throw "installing the converter requirements failed" }
}

# 3. Convert straight to Q8_0
if (-not (Test-Path $MergedDir)) { throw "merged model not found: $MergedDir (run finetune\merge_lora.py first)" }
New-Item -ItemType Directory -Force $OutDir | Out-Null
$Out = Join-Path $OutDir "qwen3.5-0.8b-$Version-Q8_0.gguf"
& "$ConvVenv\Scripts\python.exe" "$Llama\convert_hf_to_gguf.py" $MergedDir --outfile $Out --outtype q8_0
if ($LASTEXITCODE -ne 0) { throw "convert_hf_to_gguf.py failed" }

# 4. Report
$Hash = (Get-FileHash -Algorithm SHA256 $Out).Hash.ToLower()
$MB = [math]::Round((Get-Item $Out).Length / 1MB, 1)
Write-Host ""
Write-Host "GGUF   : $Out ($MB MB)"
Write-Host "sha256 : $Hash"
Write-Host ""
Write-Host "# config.env lines for the board (the GGUF is local: copy it to ~/models with scp)"
Write-Host "LLM_FILE=$(Split-Path -Leaf $Out)"
Write-Host "LLM_SHA256=$Hash"
Write-Host "LLM_ALIAS=qwen3.5-0.8b-$Version"
