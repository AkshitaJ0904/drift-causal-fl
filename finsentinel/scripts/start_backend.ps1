# Start backend with SIEM delivery worker. Token is read from file — never echoed.
$tf = "$env:USERPROFILE\.finsentinel\dev_token.txt"
if (-not (Test-Path $tf)) { Write-Error "Token file not found: $tf"; exit 1 }
$env:FINSENTINEL_AUDIT_WEBHOOK_TOKEN   = (Get-Content $tf -Raw).Trim()
$env:FINSENTINEL_AUDIT_WEBHOOK_URL     = "http://127.0.0.1:9999/ingest"
$env:FINSENTINEL_AUDIT_DELIVERY_WORKER_ENABLED = "1"
Set-Location "$PSScriptRoot\.."
& ".\venv-security\Scripts\python.exe" scripts\run_dev.py
