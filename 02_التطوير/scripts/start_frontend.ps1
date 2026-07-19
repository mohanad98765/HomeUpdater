# ================================================================
#  HomeUpdater - Frontend launcher (called from run.bat)
#  Starts Vite dev server, mirrors output to log file.
# ================================================================
param(
    [Parameter(Mandatory=$true)]
    [string]$LogFile
)

$ErrorActionPreference = "Continue"
$ScriptRoot = Split-Path $PSScriptRoot -Parent  # parent = project root (02_dev folder)
$FrontendPath = Join-Path $ScriptRoot "frontend"

Write-Host "================================================" -ForegroundColor Cyan
Write-Host "  HomeUpdater Frontend [TEST MODE]"              -ForegroundColor Cyan
Write-Host "  Log: $LogFile"                                  -ForegroundColor Gray
Write-Host "================================================" -ForegroundColor Cyan
Write-Host ""

$logDir = Split-Path $LogFile -Parent
if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir -Force | Out-Null
}

Set-Location $FrontendPath

$nodeModules = Join-Path $FrontendPath "node_modules"
if (-not (Test-Path $nodeModules)) {
    Write-Host "[X] node_modules not found at: $nodeModules" -ForegroundColor Red
    Write-Host "    Run setup.bat first." -ForegroundColor Yellow
    Read-Host "Press Enter to close"
    exit 1
}

Write-Host "[OK] Starting Vite dev server..." -ForegroundColor Green
Write-Host ""

# Run npm and mirror to log
& npm run dev 2>&1 | Tee-Object -FilePath $LogFile
