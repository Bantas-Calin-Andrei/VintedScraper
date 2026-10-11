# Registers a Windows scheduled task that starts the tracker when you log on.
# conhost --headless gives it a console with no window: on Windows 11, -WindowStyle Hidden is ignored when
# Windows Terminal is the default console, and closing that visible window kills the tracker.
$root = Split-Path -Parent $PSScriptRoot
$action = New-ScheduledTaskAction -Execute "conhost.exe" `
    -Argument "--headless powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$root\scripts\run_tracker.ps1`"" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "VintedTracker" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Vinted sell-time tracker" -Force
Write-Host "Registered. Start now with: Start-ScheduledTask -TaskName VintedTracker"
