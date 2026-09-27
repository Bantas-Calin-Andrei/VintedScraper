# Runs the tracker and restarts it if it ever exits (crash, reboot of the DB, etc.).
$ErrorActionPreference = "Continue"
Set-Location (Split-Path -Parent $PSScriptRoot)
while ($true) {
    & .\.venv\Scripts\python.exe -m vinted_tracker run
    Start-Sleep -Seconds 60
}
