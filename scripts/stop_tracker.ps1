# Stops the background tracker completely. Stopping the scheduled task alone leaves its Python process running.
Stop-ScheduledTask -TaskName VintedTracker -ErrorAction SilentlyContinue
Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -match 'vinted_tracker run' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host "Stopped tracker process $($_.ProcessId)" }
Write-Host "Tracker stopped. Start the background tracker again with: Start-ScheduledTask -TaskName VintedTracker"
