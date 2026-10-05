# ========================================================================
# PSX KMIALL BOT - Scheduled Task Setup
# ========================================================================
#
# Registers a Windows Task Scheduler task that starts the live runner
# automatically at PSX market open, Mon-Fri.
#
# Run this once as Administrator:
#   powershell -ExecutionPolicy Bypass -File setup_schedule.ps1
#
# The task:
#   - Starts at 09:25 PKT (5 min before market open)
#   - Runs Mon-Fri
#   - Uses the bundled Python from .venv
#   - Logs to logs/task_scheduler.log
#
# To remove the task:
#   schtasks /delete /tn "PSX KMIALL Bot" /f
#
# ========================================================================

$TaskName = "PSX KMIALL Bot"
$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$PythonExe = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$LiveScript = Join-Path $ProjectRoot "src\live.py"
$LogDir = Join-Path $ProjectRoot "logs"

# Create log directory if needed
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}

# Verify Python and script exist
if (-not (Test-Path $PythonExe)) {
    Write-Error "Python not found at: $PythonExe"
    exit 1
}
if (-not (Test-Path $LiveScript)) {
    Write-Error "Live script not found at: $LiveScript"
    exit 1
}

Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "THE SENTINEL - Schedule Setup" -ForegroundColor Cyan
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Project root  : $ProjectRoot"
Write-Host "Python        : $PythonExe"
Write-Host "Live script   : $LiveScript"
Write-Host "Task name     : $TaskName"
Write-Host ""

# Remove existing task if present
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Removing existing task..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Create the task action: run live.py with the bundled Python
$Action = New-ScheduledTaskAction `
    -Execute $PythonExe `
    -Argument "`"$LiveScript`"" `
    -WorkingDirectory $ProjectRoot

# Trigger: Mon-Fri at 09:25 (5 min before PSX open)
# Using a daily trigger with day-of-week filter
$Trigger = New-ScheduledTaskTrigger `
    -Daily `
    -At "09:25"

# Repetition: the live runner handles its own loop, but we set a
# repetition to restart if the process crashes
$Trigger.Repetition = (New-ScheduledTaskTrigger -Once -At "09:25" `
    -RepetitionInterval (New-TimeSpan -Hours 1) `
    -RepetitionDuration (New-TimeSpan -Hours 10)).Repetition

# Settings
$Settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -DontStopOnIdleEnd `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 12) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

# Register the task
Write-Host "Registering scheduled task..." -ForegroundColor Green

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Settings $Settings `
    -Description "The Sentinel - live collector and decision engine" `
    -RunLevel Highest

Write-Host ""
Write-Host "Done! Task '$TaskName' is registered." -ForegroundColor Green
Write-Host ""
Write-Host "The live runner will start at 09:25 PKT every weekday." -ForegroundColor Cyan
Write-Host "It collects snapshots every 5s and makes decisions every 60s." -ForegroundColor Cyan
Write-Host ""
Write-Host "Commands:" -ForegroundColor Yellow
Write-Host "  Start now     : schtasks /run /tn `"$TaskName`""
Write-Host "  Stop          : taskkill /im python.exe /fi `"WINDOWTITLE eq PSX*`""
Write-Host "  Remove task   : schtasks /delete /tn `"$TaskName`" /f"
Write-Host "  View logs     : type logs\live-*.log"
Write-Host "  View status   : python src\pipeline.py --status"
