# install_scheduler.ps1 — Register Hype Scout watchdog with Task Scheduler
# Run once as Administrator (or it will prompt for elevation)

$ProjectDir = "C:\Users\kanaw\.openclaw\workspace\ventures\hype-scout-v2"
$TaskName   = "HypeScout-Watchdog"
$ScriptPath = "$ProjectDir\scripts\watchdog.ps1"

# Remove existing task if present
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$Action  = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -WindowStyle Hidden -File `"$ScriptPath`"" `
    -WorkingDirectory $ProjectDir

# Run every 2 minutes
$Trigger = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 2) -Once -At (Get-Date)

$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1)

$Principal = New-ScheduledTaskPrincipal `
    -UserId $env:USERNAME `
    -RunLevel Highest `
    -LogonType Interactive

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Principal $Principal `
    -Description "Keeps Hype Scout scanner, poster, and Telegram bot alive" `
    -Force

Write-Host ""
Write-Host "✅ Task '$TaskName' registered — runs every 2 minutes." -ForegroundColor Green
Write-Host "   Processes will auto-restart if killed or after reboot." -ForegroundColor Gray
Write-Host ""
Write-Host "To remove: Unregister-ScheduledTask -TaskName HypeScout-Watchdog -Confirm:false" -ForegroundColor Gray
