# Everything left for the board, in one go (started by BOARD.cmd in the repo root).
#  1. SSH key login: if "ssh unoq" does not work yet, create ~/.ssh/id_ed25519_board (no passphrase),
#     add a "Host unoq" entry and install the key on the board (asks the board password ONCE).
#  2. Copy only what is missing on the board (the model is skipped when its sha256 already matches).
#  3. Run finetune/board_deploy_check.sh on the board with ssh -t (so sudo can ask for the password).
#     The script travels base64-encoded inside the ssh command: no quoting or line-ending can mangle it.
#  4. Save everything to work\fine_tuner\board_check_50.txt.
# -DryRun prints the commands instead of running ssh/scp (used to verify the exact bytes sent).
param([switch]$DryRun)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Board = "arduino@10.198.34.19"
$SshDir = Join-Path $env:USERPROFILE ".ssh"
$Key = Join-Path $SshDir "id_ed25519_board"
$Cfg = Join-Path $SshDir "config"
$Log = "work\fine_tuner\board_check_50.txt"
$Gguf = "work\fine_tuner\gguf\qwen3.5-0.8b-ft-v1-Q8_0.gguf"
$Sha = "9b5f4694609cb3d86e630e6067a0e906c99f5f751ba2840071f7a705cd5f4ad7"

function Run($exe, [string[]]$a) {
    if ($DryRun) { Write-Host "[dry-run] $exe $($a -join ' ')"; return "" }
    & $exe @a
}

# --- 1. key login ------------------------------------------------------------------------
Write-Host "=== 1/3  SSH key login"
$keyOk = $false
if (-not $DryRun -and (Test-Path $Key)) {
    & ssh -o BatchMode=yes -o ConnectTimeout=8 unoq true 2>$null
    $keyOk = ($LASTEXITCODE -eq 0)
}
if ($keyOk) {
    Write-Host "Key login already works."
} else {
    if (-not (Test-Path $SshDir)) { New-Item -ItemType Directory $SshDir | Out-Null }
    if (-not (Test-Path $Key)) {
        Run "ssh-keygen" @("-t", "ed25519", "-N", '""', "-f", $Key, "-C", "datathon-board", "-q") | Out-Null
        Write-Host "Created $Key (no passphrase)."
    }
    if (-not ((Test-Path $Cfg) -and (Select-String -Path $Cfg -Pattern '^Host unoq$' -Quiet))) {
        $entry = "`nHost unoq`n    HostName 10.198.34.19`n    User arduino`n    IdentityFile ~/.ssh/id_ed25519_board`n    IdentitiesOnly yes`n"
        if (-not $DryRun) { [IO.File]::AppendAllText($Cfg, $entry) }
        Write-Host "Added 'Host unoq' to $Cfg."
    }
    Write-Host "Installing the key on the board: type the BOARD password once."
    # Sent base64-encoded: PowerShell 5.1 mangles double quotes in native arguments.
    $installSh = "mkdir -p ~/.ssh && chmod 700 ~/.ssh && touch ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys`n" +
                 "k=`$(tr -d '\r\n')`n" +
                 "grep -qxF -- `"`$k`" ~/.ssh/authorized_keys || echo `"`$k`" >> ~/.ssh/authorized_keys`n" +
                 "echo key installed`n"
    $install = "echo $([Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($installSh))) | base64 -d > /tmp/install_key.sh && bash /tmp/install_key.sh"
    if ($DryRun) {
        [IO.File]::WriteAllText((Join-Path $env:TEMP "board_install_cmd.txt"), $install)
        Write-Host "[dry-run] (public key) | ssh $Board <install command saved to %TEMP%\board_install_cmd.txt>"
    }
    else {
        Get-Content -Raw "$Key.pub" | & ssh -o IdentitiesOnly=yes -o PreferredAuthentications=password,keyboard-interactive $Board $install
        if ($LASTEXITCODE -ne 0) { throw "Installing the key failed (wrong password, or board not reachable?)" }
        & ssh -o BatchMode=yes -o ConnectTimeout=8 unoq true
        if ($LASTEXITCODE -ne 0) { throw "Key login still fails after installing the key." }
        Write-Host "Key login works."
    }
}

# --- 2. copy only what is missing -------------------------------------------------------
Write-Host "`n=== 2/3  Files on the board"
Copy-Item results\eval-20261115-030357-ft-v1-q8-laptop.csv work\fine_tuner\ft_laptop_answers.csv -Force
# The board's data/val.jsonl must be the same (new-OCR) file as the laptop's data\val.jsonl.
$valSha = (Get-FileHash -Algorithm SHA256 data\val.jsonl).Hash.ToLower()
$state = Run "ssh" @("unoq", "cd ~/models 2>/dev/null && (echo '$Sha  qwen3.5-0.8b-ft-v1-Q8_0.gguf' | sha256sum --check --status && echo MODEL_OK); (cd ~/datathon-UPC-maths-qualcomm-arduino-unoq && echo '$valSha  data/val.jsonl' | sha256sum --check --status && echo VAL_OK); test -f ft_laptop_answers.csv && echo CSV_OK; true")
$send = @()
if ("$state" -notmatch "MODEL_OK") { $send += $Gguf }
if ("$state" -notmatch "CSV_OK") { $send += "work\fine_tuner\ft_laptop_answers.csv" }
if (-not $DryRun -and "$state" -notmatch "VAL_OK") {
    Write-Host "Board data/val.jsonl differs from the laptop's: replacing it (copy to a temp name, then rename)."
    & scp data\val.jsonl unoq:~/datathon-UPC-maths-qualcomm-arduino-unoq/data/val.jsonl.tmp
    & ssh unoq "mv -f ~/datathon-UPC-maths-qualcomm-arduino-unoq/data/val.jsonl.tmp ~/datathon-UPC-maths-qualcomm-arduino-unoq/data/val.jsonl"
}
if ($send.Count -gt 0) {
    Write-Host "Copying: $($send -join ', ')"
    Run "scp" (@($send) + @("unoq:~/models/")) | Out-Null
} else {
    Write-Host "Model (sha256 OK) and check files are already on the board: nothing to copy."
}

# --- 3. run the check on the board ------------------------------------------------------
Write-Host "`n=== 3/3  Switching the board to the fine-tuned model and testing 50 problems"
Write-Host "    (sudo on the board may ask for the board password; the 50 problems take ~10-20 minutes)"
$b64 = [Convert]::ToBase64String([IO.File]::ReadAllBytes((Join-Path $Root "finetune\board_deploy_check.sh")))
$remote = "echo $b64 | base64 -d > /tmp/ft_check.sh && bash /tmp/ft_check.sh"
if ($DryRun) {
    [IO.File]::WriteAllText((Join-Path $env:TEMP "board_remote_cmd.txt"), $remote)
    Write-Host "[dry-run] ssh -t unoq <remote command, $($remote.Length) chars, saved to %TEMP%\board_remote_cmd.txt>"
    return
}
& ssh -t unoq $remote 2>&1 | Tee-Object -FilePath $Log
Write-Host "`nSaved to $Log"
