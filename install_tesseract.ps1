# =============================================================================
#  install_tesseract.ps1
#  Installs Tesseract OCR 5.5.3 (latest stable, 2026-07-24)
#  on Windows 64-bit.  Run as Administrator for best results.
#
#  Usage (pick any one):
#    Right-click → "Run with PowerShell"  (simplest)
#    powershell -ExecutionPolicy Bypass -File install_tesseract.ps1
# =============================================================================

$ErrorActionPreference = "Stop"

# ── Configuration ─────────────────────────────────────────────────────────────
$VERSION       = "5.4.0"
$BUILD_DATE    = "20240606"
$TAG           = "v${VERSION}.${BUILD_DATE}"          # UB-Mannheim uses 'v' prefix in tag
$INSTALLER_EXE = "tesseract-ocr-w64-setup-${VERSION}.${BUILD_DATE}.exe"
$INSTALLER_URL = "https://github.com/UB-Mannheim/tesseract/releases/download/${TAG}/${INSTALLER_EXE}"
$INSTALL_DIR   = "C:\Program Files\Tesseract-OCR"
$INSTALLER     = "$env:TEMP\$INSTALLER_EXE"
$TESSDATA_DIR  = Join-Path $INSTALL_DIR "tessdata"

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Tesseract OCR $VERSION (build $BUILD_DATE) Windows Installer" -ForegroundColor Cyan
Write-Host "  Source : github.com/UB-Mannheim/tesseract (official Windows build)" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ── Admin check ───────────────────────────────────────────────────────────────
$isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole(
    [Security.Principal.WindowsBuiltInRole]::Administrator
)
if (-not $isAdmin) {
    Write-Host "[WARN] Not running as Administrator. PATH update may require a rerun as Admin." -ForegroundColor Yellow
}

# ── Already installed? ────────────────────────────────────────────────────────
$tessExe = Join-Path $INSTALL_DIR "tesseract.exe"
if (Test-Path $tessExe) {
    $existing = & $tessExe --version 2>&1 | Select-Object -First 1
    Write-Host "[INFO] Tesseract already installed: $existing" -ForegroundColor Green
    Write-Host "[INFO] Install directory : $INSTALL_DIR"
    Write-Host ""
    Write-Host "Nothing to do. Press any key to exit."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 0
}

# ── Download ──────────────────────────────────────────────────────────────────
Write-Host "[1/4] Downloading Tesseract $VERSION installer..." -ForegroundColor Yellow
Write-Host "      URL: $INSTALLER_URL"
Write-Host "      Destination: $INSTALLER"
Write-Host ""

try {
    # Use BITS if available (faster, resumable), fall back to WebClient
    if (Get-Command Start-BitsTransfer -ErrorAction SilentlyContinue) {
        Start-BitsTransfer -Source $INSTALLER_URL -Destination $INSTALLER -DisplayName "Downloading Tesseract $VERSION"
    } else {
        $wc = New-Object System.Net.WebClient
        $wc.DownloadFile($INSTALLER_URL, $INSTALLER)
    }
    Write-Host "      Download complete." -ForegroundColor Green
} catch {
    Write-Host "[ERROR] Download failed: $_" -ForegroundColor Red
    Write-Host ""
    Write-Host "Please download manually:"
    Write-Host "  $INSTALLER_URL"
    Write-Host "Then run: $INSTALLER_EXE /S"
    Write-Host ""
    Write-Host "Press any key to exit."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}

# ── Silent install ────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[2/4] Installing Tesseract silently (~1 minute)..." -ForegroundColor Yellow
Write-Host "      Target: $INSTALL_DIR"

# /S = silent, /D = destination (must be last, no trailing slash)
$proc = Start-Process -FilePath $INSTALLER `
    -ArgumentList "/S", "/D=$INSTALL_DIR" `
    -Wait -PassThru

Remove-Item $INSTALLER -Force -ErrorAction SilentlyContinue

if ($proc.ExitCode -ne 0) {
    Write-Host "[ERROR] Installer exited with code $($proc.ExitCode)" -ForegroundColor Red
    Write-Host "Press any key to exit."
    $null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
    exit 1
}
Write-Host "      Installation complete." -ForegroundColor Green

# ── English language data check ───────────────────────────────────────────────
Write-Host ""
Write-Host "[3/4] Verifying language data (eng.traineddata)..." -ForegroundColor Yellow
$engData = Join-Path $TESSDATA_DIR "eng.traineddata"
if (Test-Path $engData) {
    Write-Host "      eng.traineddata present." -ForegroundColor Green
} else {
    Write-Host "      [WARN] eng.traineddata not found — downloading separately..." -ForegroundColor Yellow
    $engUrl = "https://github.com/tesseract-ocr/tessdata_fast/raw/main/eng.traineddata"
    try {
        New-Item -ItemType Directory -Path $TESSDATA_DIR -Force | Out-Null
        $wc2 = New-Object System.Net.WebClient
        $wc2.DownloadFile($engUrl, $engData)
        Write-Host "      eng.traineddata downloaded." -ForegroundColor Green
    } catch {
        Write-Host "      [WARN] Could not auto-download traineddata: $_" -ForegroundColor Red
        Write-Host "      Download manually: $engUrl"
        Write-Host "      Place it in: $TESSDATA_DIR"
    }
}

# ── PATH update ───────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "[4/4] Updating system PATH..." -ForegroundColor Yellow
$currentPath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
if ($currentPath -notlike "*Tesseract-OCR*") {
    try {
        [System.Environment]::SetEnvironmentVariable("Path", "$currentPath;$INSTALL_DIR", "Machine")
        Write-Host "      Added to system PATH: $INSTALL_DIR" -ForegroundColor Green
    } catch {
        Write-Host "      [WARN] Could not update system PATH (requires Admin). Run as Admin to fix." -ForegroundColor Yellow
    }
} else {
    Write-Host "      Already in system PATH." -ForegroundColor Green
}
# Apply to current session immediately
$env:Path += ";$INSTALL_DIR"

# ── Verify ────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Verification:" -ForegroundColor Yellow
try {
    $verOutput = & $tessExe --version 2>&1
    $verOutput | ForEach-Object { Write-Host "  $_" -ForegroundColor Green }
} catch {
    Write-Host "  [WARN] Could not run tesseract.exe: $_" -ForegroundColor Red
}

# ── Summary ───────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  SUCCESS: Tesseract $VERSION installed!" -ForegroundColor Green
Write-Host ""
Write-Host "  Binary    : $tessExe"
Write-Host "  Tessdata  : $TESSDATA_DIR"
Write-Host ""
Write-Host "  NEXT STEPS:"
Write-Host "  1. Close and reopen your terminal / PowerShell"
Write-Host "  2. Restart the Streamlit app (run_inspection_app.bat)"
Write-Host "  3. The app will auto-detect Tesseract and enable"
Write-Host "     the dual-engine OCR fallback automatically."
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press any key to exit."
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
