# ============================================================
#  Investment Research OS — Shadow Evaluator Scheduler Installer
# ============================================================
#  独立定时任务：每周五 18:00 自动跑 shadow_evaluator.py，
#  产出可审计的 Shadow PASS/HOLD 报告（backend/output/shadow_evaluation_*.json）。
#  与 run_daily 完全解耦（观察面，不进生产链），符合 Phase 1E 边界。
#  Usage: 以管理员身份运行  .\setup_evaluator_scheduler.ps1
# ============================================================

$ErrorActionPreference = "Stop"

$TaskName    = "Investment-Research-OS_ShadowEval"
$Description = "Weekly Fri 18:00: shadow_evaluator.py (Shadow PASS/HOLD report, observation only)"
$ScriptPath  = Join-Path $PSScriptRoot "backend\shadow_evaluator.py"
$WorkDir     = Join-Path $PSScriptRoot "backend"
$PythonPath  = if ($env:WORKBUDDY_PYTHON) { $env:WORKBUDDY_PYTHON } else { "python" }
$RunTime     = "18:00"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Investment Research OS — Shadow Evaluator Scheduler" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

if (-not (Test-Path $ScriptPath)) {
    Write-Host "[ERROR] Cannot find evaluator script: $ScriptPath" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] Script:  $ScriptPath" -ForegroundColor Green
Write-Host "[OK] Python:  $PythonPath" -ForegroundColor Green
Write-Host ""

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[INFO] Task '$TaskName' exists; updating." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Host "       Old task removed."
    Write-Host ""
}

try {
    $action = New-ScheduledTaskAction `
        -Execute $PythonPath `
        -Argument "`"$ScriptPath`"" `
        -WorkingDirectory $WorkDir

    $trigger = New-ScheduledTaskTrigger `
        -Weekly `
        -DaysOfWeek Friday `
        -At $RunTime

    $settings = New-ScheduledTaskSettingsSet `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -StartWhenAvailable `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

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
    Write-Host "  Run time:    every Friday $RunTime" -ForegroundColor Cyan
    Write-Host "  Runs:        shadow_evaluator.py (observation only, no production change)" -ForegroundColor Cyan
    Write-Host "  Artifact:    backend\output\shadow_evaluation_YYYY-MM-DD.json" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Manage: taskschd.msc -> '$TaskName'" -ForegroundColor Yellow

} catch {
    Write-Host "[ERROR] Failed to create task: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "  需要管理员权限。请以管理员身份运行本脚本：" -ForegroundColor Yellow
    Write-Host "    右键 PowerShell -> 以管理员身份运行，再执行 .\setup_evaluator_scheduler.ps1" -ForegroundColor Yellow
    exit 1
}
