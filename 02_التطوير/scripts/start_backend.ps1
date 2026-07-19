# ================================================================
#  HomeUpdater - Backend launcher (called from run.bat)
#  Activates venv, starts FastAPI, mirrors output to log file.
# ================================================================
param(
    [Parameter(Mandatory=$true)]
    [string]$LogFile
)

$ErrorActionPreference = "Continue"
$ScriptRoot = Split-Path $PSScriptRoot -Parent  # parent = project root (02_dev folder)
$BackendPath = Join-Path $ScriptRoot "backend"

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  HomeUpdater Backend [TEST MODE]"               -ForegroundColor Cyan
Write-Host "  Log: $LogFile"                                  -ForegroundColor Gray
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

# Ensure log dir exists
$logDir = Split-Path $LogFile -Parent
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

# Activate venv and run uvicorn via Python
Set-Location $BackendPath

$pythonExe = Join-Path $BackendPath ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    Write-Host "[X] Python venv not found at: $pythonExe" -ForegroundColor Red
    Write-Host "    Run setup.bat first." -ForegroundColor Yellow
    Read-Host "Press Enter to close"
    exit 1
}

# ----------------------------------------------------------------
# Auto-install / refresh Python deps when requirements.txt changes.
# This avoids "module missing" crashes when we add a new dependency
# and the user forgets to re-run setup.bat.
#
# We compare the modified time of requirements.txt to a marker file.
# If requirements.txt is newer (or marker missing), run pip install.
# ----------------------------------------------------------------
$requirementsFile = Join-Path $BackendPath "requirements.txt"
$installedMarker  = Join-Path $BackendPath ".venv\.requirements_installed"

$needsInstall = $true
if ((Test-Path $installedMarker) -and (Test-Path $requirementsFile)) {
    $reqTime    = (Get-Item $requirementsFile).LastWriteTimeUtc
    $markerTime = (Get-Item $installedMarker).LastWriteTimeUtc
    if ($markerTime -ge $reqTime) {
        $needsInstall = $false
    }
}

if ($needsInstall) {
    Write-Host "[i] Installing/updating Python dependencies (requirements.txt changed)..." -ForegroundColor Yellow
    & $pythonExe -m pip install -r $requirementsFile --quiet --disable-pip-version-check
    if ($LASTEXITCODE -eq 0) {
        # Touch marker so we skip this on next start
        New-Item -Path $installedMarker -ItemType File -Force | Out-Null
        Write-Host "[OK] Dependencies up to date." -ForegroundColor Green
    } else {
        Write-Host "[!] pip install exited with code $LASTEXITCODE - continuing anyway" -ForegroundColor Yellow
    }
} else {
    Write-Host "[OK] Dependencies are up to date (cached)." -ForegroundColor DarkGray
}

Write-Host "[OK] Activating venv and starting FastAPI..." -ForegroundColor Green
Write-Host ""

# Start the backend, piping all output through Tee-Object so it appears
# both in this window and in the log file.
& $pythonExe -m app.main 2>&1 | Tee-Object -FilePath $LogFile
