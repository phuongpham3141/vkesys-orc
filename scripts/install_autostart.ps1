<#
.SYNOPSIS
  Dang ky VIC OCR auto-start moi khi user dang nhap Windows.

.DESCRIPTION
  Tao Scheduled Task ten "VIC OCR Auto Start" chay start.bat lan duy nhat
  moi lan user dang nhap. Task Scheduler tu lo:
    - Restart neu start.bat crash
    - Chay voi quyen highest (du de spawn console window)
    - Khong dung khi may chay pin (chi may server, khong quan tam)
  Cua so Flask + Scheduler se hien tren desktop nhu khi double-click.

  Yeu cau quyen Administrator de tao task.

.PARAMETER TaskName
  Ten task trong Task Scheduler. Mac dinh: "VIC OCR Auto Start"

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install_autostart.ps1
#>
[CmdletBinding()]
param(
    [string]$TaskName = "VIC OCR Auto Start"
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $PSScriptRoot
$startBat = Join-Path $projectRoot "start.bat"

if (-not (Test-Path $startBat)) {
    throw "Khong tim thay $startBat"
}

# Chac chan running as admin
$currentUser = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $currentUser.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Script can quyen Administrator. Mo PowerShell 'Run as administrator' va chay lai."
    exit 1
}

Write-Host "=== VIC OCR Auto-Start Installer ==="
Write-Host "Project root: $projectRoot"
Write-Host "Task name:    $TaskName"
Write-Host ""

# Xoa task cu neu co
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[..] Xoa task cu..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

# Action: chay start.bat trong working dir = project root
$action = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c start `"`" `"$startBat`"" `
    -WorkingDirectory $projectRoot

# Trigger: moi lan user dang nhap
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"

# Settings: dung policy cho server lon
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -DontStopOnIdleEnd `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -StartWhenAvailable

# Principal: chay voi quyen highest cua user hien tai
$principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType Interactive `
    -RunLevel Highest

# Register
Register-ScheduledTask `
    -TaskName $TaskName `
    -Description "Tu dong khoi dong VIC OCR (Flask web + scheduler) khi user dang nhap." `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal | Out-Null

Write-Host "[OK] Da dang ky task '$TaskName'"
Write-Host ""
Write-Host "Verify:"
Get-ScheduledTask -TaskName $TaskName | Format-List TaskName, State, NextRunTime, LastRunTime
Write-Host ""
Write-Host "=== Cach kiem tra: ==="
Write-Host "  - Mo Task Scheduler (taskschd.msc), tim '$TaskName' trong Task Scheduler Library"
Write-Host "  - Hoac chay: Get-ScheduledTask -TaskName '$TaskName'"
Write-Host "  - De test ngay: Start-ScheduledTask -TaskName '$TaskName'"
Write-Host ""
Write-Host "=== Cach go bo: ==="
Write-Host "  powershell -ExecutionPolicy Bypass -File scripts\uninstall_autostart.ps1"
