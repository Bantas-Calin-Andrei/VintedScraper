# Registers a Windows scheduled task that starts the tracker when you log on.
$root = Split-Path -Parent $PSScriptRoot
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$root\scripts\run_tracker.ps1`"" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "VintedTracker" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Vinted sell-time tracker" -Force
Write-Host "Registered. Start now with: Start-ScheduledTask -TaskName VintedTracker"
