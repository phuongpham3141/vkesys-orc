<#
.SYNOPSIS
  Tu dong cai dat Tesseract-OCR 5.5.0 (UB Mannheim build) + Vietnamese language data.

.DESCRIPTION
  Khong can input — chay 1 lan, hoan toan idempotent. Tai installer ky boi
  Universitat Mannheim, cai vao "C:\Program Files\Tesseract-OCR", tai
  vie.traineddata (best model) tu tessdata_best, va them duong dan vao
  User PATH.

.NOTES
  Yeu cau quyen Administrator de ghi vao Program Files.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\install_tesseract.ps1
#>
[CmdletBinding()]
param(
    [string]$InstallDir = "C:\Program Files\Tesseract-OCR",
    [string]$InstallerUrl = "https://github.com/tesseract-ocr/tesseract/releases/download/5.5.0/tesseract-ocr-w64-setup-5.5.0.20241111.exe",
    [string]$VieDataUrl = "https://github.com/tesseract-ocr/tessdata_best/raw/main/vie.traineddata"
)

$ErrorActionPreference = "Stop"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$ProgressPreference = 'SilentlyContinue'

Write-Host "=== Tesseract-OCR auto-installer ==="

# 1. Tesseract binary -------------------------------------------------------
$tessExe = Join-Path $InstallDir "tesseract.exe"
if (Test-Path $tessExe) {
    Write-Host "[OK] Tesseract da cai san: $tessExe"
} else {
    $installer = Join-Path $env:TEMP "tesseract-installer.exe"
    if (-not (Test-Path $installer)) {
        Write-Host "[..] Tai installer tu $InstallerUrl"
        Invoke-WebRequest -Uri $InstallerUrl -OutFile $installer -UseBasicParsing
    }
    $sig = Get-AuthenticodeSignature $installer
    if ($sig.SignerCertificate -and $sig.SignerCertificate.Subject -notmatch "Mannheim") {
        Write-Warning "Installer signer khong khop Mannheim: $($sig.SignerCertificate.Subject)"
    }
    Write-Host "[..] Cai silent vao $InstallDir"
    Start-Process -FilePath $installer -ArgumentList "/S","/D=$InstallDir" -Wait
    if (-not (Test-Path $tessExe)) {
        throw "Cai dat that bai: khong tim thay $tessExe"
    }
    Write-Host "[OK] Da cai Tesseract"
}

& $tessExe --version 2>&1 | Select-Object -First 1 | Write-Host

# 2. Vietnamese language data ----------------------------------------------
$vieFile = Join-Path $InstallDir "tessdata\vie.traineddata"
if (Test-Path $vieFile) {
    Write-Host "[OK] vie.traineddata da co"
} else {
    Write-Host "[..] Tai vie.traineddata"
    Invoke-WebRequest -Uri $VieDataUrl -OutFile $vieFile -UseBasicParsing
    Write-Host "[OK] Da tai vie.traineddata"
}

# 3. PATH -------------------------------------------------------------------
$userPath = [Environment]::GetEnvironmentVariable("PATH", "User")
$paths = if ($userPath) { $userPath -split ";" } else { @() }
if ($paths -contains $InstallDir) {
    Write-Host "[OK] $InstallDir da co trong User PATH"
} else {
    $newPath = if ($userPath) { "$userPath;$InstallDir" } else { $InstallDir }
    [Environment]::SetEnvironmentVariable("PATH", $newPath, "User")
    Write-Host "[OK] Them $InstallDir vao User PATH (mo shell moi de co hieu luc)"
}

Write-Host ""
Write-Host "Languages co san:"
& $tessExe --list-langs 2>&1 | Select-Object -Skip 1 | ForEach-Object { "  - $_" }
Write-Host ""
Write-Host "=== Hoan tat. .env da tro san vao $tessExe ==="
