<#
.SYNOPSIS
  Dang ky VIC OCR Watchdog vao Task Scheduler — chay moi 15 phut.

.DESCRIPTION
  Tao Scheduled Task ten "VIC OCR Watchdog" chay scripts\health_check.py
  moi 15 phut bang pythonw.exe (no console window). Watchdog tu kiem tra:
    - Flask web (port 8000) — restart neu chet
    - Scheduler heartbeat — restart neu stale > 5 phut
    - Job 'processing' qua 60 phut — reset/fail

  Chay luc startup + moi 15 phut sau do. RunLevel=Highest, no batteries restriction.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install_watchdog.ps1
#>
[CmdletBinding()]
param(
    [string]$TaskName = "VIC OCR Watchdog",
    [int]$IntervalMinutes = 15
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $projectRoot "venv\Scripts\pythonw.exe"
$pyHealth = Join-Path $projectRoot "venv\Scripts\python.exe"
$healthScript = Join-Path $projectRoot "scripts\health_check.py"

# pythonw is preferred (silent), fall back to python if missing
if (Test-Path $pythonw) {
    $exe = $pythonw
} else {
    $exe = $pyHealth
    Write-Warning "pythonw.exe not found — using python.exe (will flash console briefly each run)"
}
if (-not (Test-Path $exe)) {
    throw "Khong tim thay $exe — chay start.bat truoc de tao venv."
}
if (-not (Test-Path $healthScript)) {
    throw "Khong tim thay $healthScript"
}

# Require admin
$currentUser = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $currentUser.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Script can quyen Administrator. Mo PowerShell 'Run as administrator'."
}

Write-Host "=== VIC OCR Watchdog Installer ==="
Write-Host "Project root: $projectRoot"
Write-Host "Task name:    $TaskName"
Write-Host "Python:       $exe"
Write-Host "Script:       $healthScript"
Write-Host "Interval:     every $IntervalMinutes minutes"
Write-Host ""

# Drop old task if any
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[..] Removing existing task..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Action: pythonw.exe scripts\health_check.py
$action = New-ScheduledTaskAction `
    -Execute $exe `
    -Argument "`"$healthScript`"" `
    -WorkingDirectory $projectRoot

# Triggers: at startup AND every N minutes (use 2 triggers; second is repetition)
$triggerStartup = New-ScheduledTaskTrigger -AtStartup
$triggerRepeat  = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)

# Settings — be patient + run even on battery (server)
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -DontStopOnIdleEnd `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -MultipleInstances IgnoreNew

# Run as SYSTEM so it works even when no user is logged in (web server scenario)
$principal = New-ScheduledTaskPrincipal `
    -UserId "NT AUTHORITY\SYSTEM" `
    -LogonType ServiceAccount `
    -RunLevel Highest

Register-ScheduledTask `
    -TaskName $TaskName `
    -Description "Tu kiem tra suc khoe VIC OCR moi $IntervalMinutes phut + restart neu can." `
    -Action $action `
    -Trigger @($triggerStartup, $triggerRepeat) `
    -Settings $settings `
    -Principal $principal | Out-Null

Write-Host "[OK] Task '$TaskName' registered"
Write-Host ""
Write-Host "Verify:"
Get-ScheduledTask -TaskName $TaskName | Format-List TaskName, State, NextRunTime, LastRunTime

Write-Host ""
Write-Host "=== Test ngay (1 lan): ==="
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "  tail -f logs\health.log"
Write-Host ""
Write-Host "=== Go bo: ==="
Write-Host "  scripts\uninstall_watchdog.ps1 (hoac uninstall_watchdog.bat)"
