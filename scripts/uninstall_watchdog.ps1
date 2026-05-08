<#
.SYNOPSIS
  Go bo VIC OCR Watchdog scheduled task.
#>
[CmdletBinding()]
param(
    [string]$TaskName = "VIC OCR Watchdog"
)

$ErrorActionPreference = "Stop"

$currentUser = New-Object Security.Principal.WindowsPrincipal(
    [Security.Principal.WindowsIdentity]::GetCurrent()
)
if (-not $currentUser.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Can quyen Administrator."
}

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if (-not $existing) {
    Write-Host "Task '$TaskName' khong ton tai. Khong co gi de go."
    exit 0
}

Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
Write-Host "[OK] Da go '$TaskName'"
