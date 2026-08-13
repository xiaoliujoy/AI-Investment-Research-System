# ============================================================
#  Investment Research OS — Windows Scheduler Installer
# ============================================================
#  Installs a scheduled task that runs the daily pipeline at 08:30
#  on every weekday (data collect -> decision tree -> CIO memo, no push).
#  Usage: right-click -> "Run with PowerShell", or: .\setup_scheduler.ps1
# ============================================================

$ErrorActionPreference = "Stop"

# ---- Config ----
$TaskName    = "Investment-Research-OS_Daily"
$Description = "Weekdays 08:30: data collect -> 8-layer decision tree -> CIO memo (no push)"
$ScriptPath  = Join-Path $PSScriptRoot "backend\run_daily.py"
$WorkDir     = Join-Path $PSScriptRoot "backend"
$PythonPath  = if ($env:WORKBUDDY_PYTHON) { $env:WORKBUDDY_PYTHON } else { "python" }
$RunTime     = "08:30"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Investment Research OS — Scheduler Install" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ---- Pre-flight checks ----
if (-not (Test-Path $ScriptPath)) {
    Write-Host "[ERROR] Cannot find pipeline script: $ScriptPath" -ForegroundColor Red
    Write-Host "Please confirm the repo path is correct." -ForegroundColor Red
    exit 1
}

Write-Host "[OK] Script:  $ScriptPath" -ForegroundColor Green
Write-Host "[OK] Python:  $PythonPath  (override with `$env:WORKBUDDY_PYTHON)" -ForegroundColor Green
Write-Host ""

# ---- Remove existing task if present ----
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[INFO] Task '$TaskName' exists; updating." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "       Old task removed."
    Write-Host ""
}

# ---- Create task ----
try {
    $action = New-ScheduledTaskAction `
        -Execute $PythonPath `
        -Argument "`"$ScriptPath`" --memo-only" `
        -WorkingDirectory $WorkDir

    $trigger = New-ScheduledTaskTrigger `
        -Weekly `
        -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
        -At $RunTime

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 90)

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description $Description `
        -Force

    Write-Host "[OK] Scheduled task installed!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Task name:   $TaskName" -ForegroundColor Cyan
    Write-Host "  Run time:    every weekday $RunTime" -ForegroundColor Cyan
    Write-Host "  Runs:        run_daily.py (collect -> decision tree -> CIO memo)" -ForegroundColor Cyan
    Write-Host "  Artifacts:   backend\output\memo_YYYY-MM-DD_wechat.html" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Manage: taskschd.msc -> '$TaskName'" -ForegroundColor Yellow

} catch {
    Write-Host "[ERROR] Failed to create task: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "  Manual steps:" -ForegroundColor Yellow
    Write-Host "    1. taskschd.msc -> Create Basic Task: $TaskName" -ForegroundColor Yellow
    Write-Host "    2. Trigger: Daily $RunTime, weekdays only" -ForegroundColor Yellow
    Write-Host "    3. Action: Start a program" -ForegroundColor Yellow
    Write-Host "       Program: $PythonPath" -ForegroundColor Yellow
    Write-Host "       Args:    `"$ScriptPath`" --memo-only" -ForegroundColor Yellow
    Write-Host "       Startin: $WorkDir" -ForegroundColor Yellow
    Write-Host ""
}
