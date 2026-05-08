<#
.SYNOPSIS
  Dang ky VIC OCR Watchdog vao Task Scheduler — chay moi 15 phut.

.DESCRIPTION
  Tao Scheduled Task ten "VIC OCR Watchdog" chay scripts\health_check.py
  bang pythonw.exe (silent, no console window) moi 15 phut + AtStartup.

  Hai mode tu chon dua tren quyen:
    - Admin       → principal = SYSTEM, RunLevel = Highest, Logon = ServiceAccount.
                    Chay BAT KE user logged-in hay khong (server scenario).
    - Non-admin   → principal = current user, RunLevel = Limited.
                    Chi chay khi user da login. Du cho dev box.

  Idempotent: chay lai an toan — task duoc replace.

.PARAMETER Silent
  Khong in nhieu output (dung khi goi tu start.bat).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install_watchdog.ps1
#>
[CmdletBinding()]
param(
    [string]$TaskName = "VIC OCR Watchdog",
    [int]$IntervalMinutes = 15,
    [switch]$Silent
)

$ErrorActionPreference = "Stop"

function Write-Info { param($msg) if (-not $Silent) { Write-Host $msg } }

$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $projectRoot "venv\Scripts\pythonw.exe"
$pyHealth = Join-Path $projectRoot "venv\Scripts\python.exe"
$healthScript = Join-Path $projectRoot "scripts\health_check.py"

if (Test-Path $pythonw) {
    $exe = $pythonw
} elseif (Test-Path $pyHealth) {
    $exe = $pyHealth
} else {
    Write-Warning "venv chua duoc tao. Chay start.bat truoc."
    exit 2
}
if (-not (Test-Path $healthScript)) {
    Write-Warning "Khong tim thay $healthScript"
    exit 2
}

# Check admin
$currentUser = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
$isAdmin = $currentUser.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)

Write-Info "=== VIC OCR Watchdog Installer ==="
Write-Info "Mode: $(if ($isAdmin) { 'ADMIN (SYSTEM principal — fires regardless of login)' } else { 'USER (current user — fires when logged in)' })"
Write-Info ""

# Drop old task if any
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    Write-Info "  Replaced existing task"
}

$action = New-ScheduledTaskAction `
    -Execute $exe `
    -Argument "`"$healthScript`"" `
    -WorkingDirectory $projectRoot

# Triggers: at startup AND every N minutes
$triggerStartup = New-ScheduledTaskTrigger -AtStartup
$triggerRepeat  = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -DontStopOnIdleEnd `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 5) `
    -MultipleInstances IgnoreNew

if ($isAdmin) {
    $principal = New-ScheduledTaskPrincipal `
        -UserId "NT AUTHORITY\SYSTEM" `
        -LogonType ServiceAccount `
        -RunLevel Highest
} else {
    $principal = New-ScheduledTaskPrincipal `
        -UserId "$env:USERDOMAIN\$env:USERNAME" `
        -LogonType Interactive `
        -RunLevel Limited
}

try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Description "Tu kiem tra suc khoe VIC OCR moi $IntervalMinutes phut + restart neu can." `
        -Action $action `
        -Trigger @($triggerStartup, $triggerRepeat) `
        -Settings $settings `
        -Principal $principal | Out-Null
    Write-Info "[OK] Task '$TaskName' registered (every $IntervalMinutes min)"
    exit 0
} catch {
    Write-Warning "Failed to register task: $_"
    exit 1
}
