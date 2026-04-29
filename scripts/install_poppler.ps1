<#
.SYNOPSIS
  Tu dong tai va cai dat Poppler-Windows (release moi nhat).

.DESCRIPTION
  Lay release moi nhat tu oschwartz10612/poppler-windows qua GitHub API,
  giai nen vao "C:\Program Files\poppler", them bin vao User PATH va in
  ra duong dan can set cho POPPLER_PATH trong .env. Idempotent.

.NOTES
  Yeu cau quyen Administrator de ghi vao Program Files.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install_poppler.ps1
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "C:\Program Files\poppler"
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = 'SilentlyContinue'

Write-Host "=== Poppler-Windows auto-installer ==="

$binDir = Join-Path $InstallDir "Library\bin"
if (Test-Path "$binDir\pdfinfo.exe") {
    Write-Host "[OK] Poppler da cai san: $binDir"
} else {
    $api = "https://api.github.com/repos/oschwartz10612/poppler-windows/releases/latest"
    $rel = Invoke-RestMethod -Uri $api -UseBasicParsing -Headers @{ "User-Agent" = "vic-ocr" }
    $asset = $rel.assets | Where-Object { $_.name -like "Release-*.zip" } | Select-Object -First 1
    if (-not $asset) { throw "Khong tim thay Release zip trong release moi nhat" }
    Write-Host "[..] Release: $($rel.tag_name)  ($([math]::Round($asset.size / 1MB, 1)) MB)"

    $zipPath = Join-Path $env:TEMP "poppler.zip"
    Invoke-WebRequest -Uri $asset.browser_download_url -OutFile $zipPath -UseBasicParsing

    $tempExtract = Join-Path $env:TEMP "poppler-extract"
    if (Test-Path $tempExtract) { Remove-Item -Recurse -Force $tempExtract }
    Expand-Archive -Path $zipPath -DestinationPath $tempExtract
    $inner = Get-ChildItem $tempExtract | Where-Object { $_.PSIsContainer } | Select-Object -First 1
    if (-not $inner) { throw "Zip rong" }
    if (Test-Path $InstallDir) { Remove-Item -Recurse -Force $InstallDir }
    Move-Item -Path $inner.FullName -Destination $InstallDir
    Remove-Item -Recurse -Force $tempExtract
    Write-Host "[OK] Da giai nen vao $InstallDir"
}

if (-not (Test-Path "$binDir\pdfinfo.exe")) {
    throw "Cai dat that bai: khong tim thay $binDir\pdfinfo.exe"
}

# Add to user PATH
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
if (($userPath -split ";") -contains $binDir) {
    Write-Host "[OK] $binDir da co trong User PATH"
} else {
    $newPath = if ($userPath) { "$userPath;$binDir" } else { $binDir }
    [Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
    Write-Host "[OK] Them $binDir vao User PATH"
}

Write-Host ""
Write-Host "Trong .env hay set:"
Write-Host "  POPPLER_PATH=$binDir"
Write-Host ""
Write-Host "=== Hoan tat ==="
