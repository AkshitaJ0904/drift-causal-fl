# Start the SIEM forwarder. Token is read from file — never echoed.
$tf = "$env:USERPROFILE\.finsentinel\dev_token.txt"
if (-not (Test-Path $tf)) { Write-Error "Token file not found: $tf"; exit 1 }
$env:FINSENTINEL_AUDIT_WEBHOOK_TOKEN = (Get-Content $tf -Raw).Trim()
$env:FINSENTINEL_SIEM_LOG = "logs\finsentinel-siem.jsonl"
Set-Location "$PSScriptRoot\.."
& ".\venv-security\Scripts\python.exe" scripts\siem_forwarder.py
