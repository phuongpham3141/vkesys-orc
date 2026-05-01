<#
.SYNOPSIS
  Go bo VIC OCR Auto-Start scheduled task.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\uninstall_autostart.ps1
#>
[CmdletBinding()]
param(
    [string]$TaskName = "VIC OCR Auto Start"
)

$ErrorActionPreference = "Stop"

$currentUser = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $currentUser.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Script can quyen Administrator."
    exit 1
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "Task '$TaskName' khong ton tai. Khong co gi de go."
    exit 0
}

Write-Host "[..] Xoa task '$TaskName'..."
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "[OK] Da go autostart."
