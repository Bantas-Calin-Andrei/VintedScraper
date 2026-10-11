# Runs the dashboard and restarts it if it ever exits.
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)
while ($true) {
    & .\.venv\Scripts\python.exe -m vinted_tracker dashboard
    Start-Sleep -Seconds 30
}
