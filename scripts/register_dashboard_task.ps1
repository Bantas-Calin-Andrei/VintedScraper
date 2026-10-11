# Registers a Windows scheduled task that starts the dashboard (http://localhost:8000) when you log on, with no window.
$root = Split-Path -Parent $PSScriptRoot
$action = New-ScheduledTaskAction -Execute "conhost.exe" `
    -Argument "--headless powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$root\scripts\run_dashboard.ps1`"" `
    -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName "VintedDashboard" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Vinted tracker dashboard on http://localhost:8000" -Force
Write-Host "Registered. Start now with: Start-ScheduledTask -TaskName VintedDashboard"
