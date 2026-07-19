# ================================================================
#  HomeUpdater - Setup PowerShell Script
#  ASCII-only. Direct-download installers (no winget dependency).
#  Logs everything via Start-Transcript when -LogFile is given.
#
#  Installs (only what is missing): Python 3.12, Node.js 20 LTS, Nmap, Git
#  Sets up: Python venv, Frontend dependencies, runtime dirs
# ================================================================
param(
    [string]$LogFile = ""
)

$ErrorActionPreference = "Stop"
$ScriptRoot = $PSScriptRoot

# ---------- Start full transcript logging ----------
if ($LogFile -ne "") {
    try {
        $logDir = Split-Path $LogFile -Parent
        if (-not (Test-Path $logDir)) {
            New-Item -ItemType Directory -Path $logDir -Force | Out-Null
        }
        Start-Transcript -Path $LogFile -Force | Out-Null
        Write-Host "[i] Transcript logging to: $LogFile"
    }
    catch {
        Write-Host "[!] Could not start transcript: $_"
    }
}

# ---------- Output helpers ----------
function Write-Step    { param($msg) Write-Host "`n[->] $msg" -ForegroundColor Cyan }
function Write-Success { param($msg) Write-Host "[OK] $msg" -ForegroundColor Green }
function Write-Warn    { param($msg) Write-Host "[!]  $msg" -ForegroundColor Yellow }
function Write-Err     { param($msg) Write-Host "[X]  $msg" -ForegroundColor Red }
function Write-Info    { param($msg) Write-Host "     $msg" -ForegroundColor Gray }

Write-Host @"
============================================================
  HomeUpdater - Development Environment Setup
  TEST MODE - not for production yet
  Method: direct-download installers (winget-free)
============================================================
"@ -ForegroundColor Magenta

# ----------------------------------------------------------------
# TLS 1.2 (older Windows defaults to 1.0/1.1, breaks some HTTPS)
# ----------------------------------------------------------------
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

# ----------------------------------------------------------------
# Cache directory for installers (avoid re-downloading on retry)
# ----------------------------------------------------------------
$InstallerCache = Join-Path $env:TEMP "HomeUpdater-Installers"
if (-not (Test-Path $InstallerCache)) {
    New-Item -ItemType Directory -Path $InstallerCache -Force | Out-Null
}
Write-Info "Installer cache: $InstallerCache"

# ----------------------------------------------------------------
# Helper: Refresh PATH from machine + user environment
# ----------------------------------------------------------------
function Update-Path {
    $machine = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
    $user    = [System.Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user"
}

# ----------------------------------------------------------------
# Helper: Test if a tool is installed and matches version regex
# ----------------------------------------------------------------
function Test-Tool {
    param($Cmd, $Arg, $Regex)
    try {
        $output = & $Cmd $Arg 2>&1
        if ($output -match $Regex) { return $output }
    }
    catch { }
    return $null
}

# ----------------------------------------------------------------
# Helper: Download a file with progress
# ----------------------------------------------------------------
function Get-File {
    param($Url, $OutFile)
    if (Test-Path $OutFile) {
        Write-Info "Cached: $OutFile"
        return
    }
    Write-Info "Downloading: $Url"
    Write-Info "  -> $OutFile"
    $progressPreference = 'silentlyContinue'
    try {
        Invoke-WebRequest -Uri $Url -OutFile $OutFile -UseBasicParsing -TimeoutSec 600
        Write-Success "Downloaded ($([math]::Round((Get-Item $OutFile).Length / 1MB, 1)) MB)"
    }
    catch {
        Write-Err "Download failed: $_"
        throw
    }
}

# ----------------------------------------------------------------
# Helper: Run an installer and wait
# ----------------------------------------------------------------
function Invoke-Installer {
    param(
        [string]$Path,
        [string[]]$Arguments,
        [bool]$IsMsi = $false
    )
    if ($IsMsi) {
        $msiArgs = @("/i", "`"$Path`"") + $Arguments
        Write-Info "msiexec $($msiArgs -join ' ')"
        $proc = Start-Process -FilePath "msiexec.exe" -ArgumentList $msiArgs -Wait -PassThru -NoNewWindow
    }
    else {
        Write-Info "$Path $($Arguments -join ' ')"
        $proc = Start-Process -FilePath $Path -ArgumentList $Arguments -Wait -PassThru -NoNewWindow
    }
    return $proc.ExitCode
}

# ----------------------------------------------------------------
# Tool definitions (direct-download URLs from official sources)
# ----------------------------------------------------------------
$tools = @(
    @{
        Name              = "Python 3.12"
        VerifyCmd         = "python"
        VersionArg        = "--version"
        VersionRegex      = "Python 3\.(1[1-9]|[2-9]\d)"
        DownloadUrl       = "https://www.python.org/ftp/python/3.12.8/python-3.12.8-amd64.exe"
        InstallerFile     = "python-3.12.8-amd64.exe"
        IsMsi             = $false
        SilentArgs        = @("/quiet", "InstallAllUsers=1", "PrependPath=1", "Include_test=0", "SimpleInstall=1", "AssociateFiles=1", "Shortcuts=0")
    },
    @{
        Name              = "Node.js 20 LTS"
        VerifyCmd         = "node"
        VersionArg        = "--version"
        VersionRegex      = "v(1[8-9]|2\d)\."
        DownloadUrl       = "https://nodejs.org/dist/v20.18.1/node-v20.18.1-x64.msi"
        InstallerFile     = "node-v20.18.1-x64.msi"
        IsMsi             = $true
        SilentArgs        = @("/qn", "/norestart", "ALLUSERS=1", "ADDLOCAL=ALL")
    },
    @{
        Name              = "Nmap"
        VerifyCmd         = "nmap"
        VersionArg        = "--version"
        VersionRegex      = "Nmap version"
        DownloadUrl       = "https://nmap.org/dist/nmap-7.95-setup.exe"
        InstallerFile     = "nmap-7.95-setup.exe"
        IsMsi             = $false
        SilentArgs        = @("/S")
    },
    @{
        Name              = "Git for Windows"
        VerifyCmd         = "git"
        VersionArg        = "--version"
        VersionRegex      = "git version"
        DownloadUrl       = "https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/Git-2.47.1-64-bit.exe"
        InstallerFile     = "Git-2.47.1-64-bit.exe"
        IsMsi             = $false
        SilentArgs        = @("/VERYSILENT", "/NORESTART", "/NOCANCEL", "/SP-", "/SUPPRESSMSGBOXES", "/CLOSEAPPLICATIONS", "/RESTARTAPPLICATIONS")
    }
)

# ----------------------------------------------------------------
# Step 1-4: Install missing tools
# ----------------------------------------------------------------
Update-Path

foreach ($tool in $tools) {
    Write-Step "Checking $($tool.Name)..."

    $existing = Test-Tool -Cmd $tool.VerifyCmd -Arg $tool.VersionArg -Regex $tool.VersionRegex
    if ($existing) {
        Write-Success "$($tool.Name) already installed: $existing"
        continue
    }

    Write-Warn "$($tool.Name) is missing. Will install..."

    try {
        $installerPath = Join-Path $InstallerCache $tool.InstallerFile

        Get-File -Url $tool.DownloadUrl -OutFile $installerPath

        Write-Info "Running silent installer (this may take a few minutes)..."
        $exitCode = Invoke-Installer -Path $installerPath -Arguments $tool.SilentArgs -IsMsi $tool.IsMsi

        if ($exitCode -ne 0 -and $exitCode -ne 3010) {
            # 3010 = success, reboot required
            Write-Warn "Installer exited with code $exitCode (continuing anyway)"
        }

        Update-Path

        # Re-verify
        $verify = Test-Tool -Cmd $tool.VerifyCmd -Arg $tool.VersionArg -Regex $tool.VersionRegex
        if ($verify) {
            Write-Success "$($tool.Name) installed: $verify"
        }
        else {
            Write-Warn "$($tool.Name) installed but not on PATH yet - may need a new shell session."
        }
    }
    catch {
        Write-Err "Failed to install $($tool.Name): $_"
        Write-Info "You can install it manually from: $($tool.DownloadUrl)"
        # Continue trying other tools - Python/Node are critical, Nmap/Git can be added later.
    }
}

# ----------------------------------------------------------------
# Final environment refresh
# ----------------------------------------------------------------
Write-Step "Refreshing environment PATH..."
Update-Path
Write-Success "PATH refreshed."

# ----------------------------------------------------------------
# Step 5: Set up Backend (Python virtual environment)
# ----------------------------------------------------------------
Write-Step "Setting up Backend (Python venv)..."

$backendPath = Join-Path $ScriptRoot "backend"
if (-not (Test-Path $backendPath)) {
    Write-Err "backend folder not found at: $backendPath"
    if ($LogFile -ne "") { try { Stop-Transcript | Out-Null } catch {} }
    exit 1
}

# Find python.exe (PATH may not be refreshed in current session for newly-installed Python)
$pythonExe = "python"
$pythonAvailable = Test-Tool -Cmd $pythonExe -Arg "--version" -Regex "Python 3\."
if (-not $pythonAvailable) {
    # Try common installation paths
    $candidates = @(
        "${env:ProgramFiles}\Python312\python.exe",
        "${env:ProgramFiles(x86)}\Python312\python.exe",
        "${env:LocalAppData}\Programs\Python\Python312\python.exe"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $pythonExe = $c; $pythonAvailable = $true; break }
    }
}
if (-not $pythonAvailable) {
    Write-Err "Python is not on PATH. Restart this script after restarting your terminal/PC."
    if ($LogFile -ne "") { try { Stop-Transcript | Out-Null } catch {} }
    exit 1
}
Write-Info "Using Python at: $pythonExe"

Push-Location $backendPath
try {
    if (-not (Test-Path ".venv")) {
        Write-Info "Creating Python virtual environment (.venv)..."
        & $pythonExe -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw "Failed to create venv" }
    }
    else {
        Write-Info ".venv already exists"
    }

    Write-Info "Installing Python dependencies..."
    & ".\.venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
    & ".\.venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet

    if ($LASTEXITCODE -eq 0) {
        Write-Success "Backend ready."
    }
    else {
        throw "Failed to install Python dependencies"
    }
}
catch {
    Write-Err "Backend setup error: $_"
    Pop-Location
    if ($LogFile -ne "") { try { Stop-Transcript | Out-Null } catch {} }
    exit 1
}
Pop-Location

# ----------------------------------------------------------------
# Step 6: Set up Frontend (Node modules)
# ----------------------------------------------------------------
Write-Step "Setting up Frontend (npm install)..."

$frontendPath = Join-Path $ScriptRoot "frontend"
if (-not (Test-Path $frontendPath)) {
    Write-Err "frontend folder not found at: $frontendPath"
    if ($LogFile -ne "") { try { Stop-Transcript | Out-Null } catch {} }
    exit 1
}

# Find npm.cmd
$npmCmd = "npm"
$npmAvailable = $false
try {
    $null = & $npmCmd --version 2>&1
    if ($LASTEXITCODE -eq 0) { $npmAvailable = $true }
}
catch { }
if (-not $npmAvailable) {
    $candidates = @(
        "${env:ProgramFiles}\nodejs\npm.cmd",
        "${env:ProgramFiles(x86)}\nodejs\npm.cmd"
    )
    foreach ($c in $candidates) {
        if (Test-Path $c) { $npmCmd = $c; $npmAvailable = $true; break }
    }
}
if (-not $npmAvailable) {
    Write-Err "npm is not on PATH. Restart this script after restarting your terminal/PC."
    if ($LogFile -ne "") { try { Stop-Transcript | Out-Null } catch {} }
    exit 1
}
Write-Info "Using npm at: $npmCmd"

Push-Location $frontendPath
try {
    Write-Info "Installing npm packages... (may take several minutes)"
    & $npmCmd install --silent --no-audit --no-fund 2>&1 | Out-Null

    if ($LASTEXITCODE -eq 0 -or (Test-Path "node_modules")) {
        Write-Success "Frontend ready."
    }
    else {
        throw "npm install failed"
    }
}
catch {
    Write-Err "Frontend setup error: $_"
    Pop-Location
    if ($LogFile -ne "") { try { Stop-Transcript | Out-Null } catch {} }
    exit 1
}
Pop-Location

# ----------------------------------------------------------------
# Step 7: Create runtime directories
# ----------------------------------------------------------------
Write-Step "Creating runtime directories..."

$runtimeDirs = @("logs", "data")
foreach ($dir in $runtimeDirs) {
    $path = Join-Path $ScriptRoot $dir
    if (-not (Test-Path $path)) {
        New-Item -ItemType Directory -Path $path | Out-Null
        Write-Success "Created: $dir/"
    }
    else {
        Write-Info "Already exists: $dir/"
    }
}

# ----------------------------------------------------------------
# Step 8: Final verification
# ----------------------------------------------------------------
Write-Step "Final verification..."

$checks = @(
    @{ Test = { (Test-Tool -Cmd $pythonExe -Arg "--version" -Regex "Python 3\.") -ne $null }; Msg = "Python works" }
    @{ Test = { (Test-Tool -Cmd $npmCmd     -Arg "--version" -Regex "\d+\.\d+") -ne $null };   Msg = "npm works" }
    @{ Test = { Test-Path "$ScriptRoot\backend\.venv\Scripts\python.exe" }; Msg = "Python venv ready" }
    @{ Test = { Test-Path "$ScriptRoot\frontend\node_modules" };           Msg = "node_modules present" }
)

# Optional checks (don't fail setup if missing)
$optionalChecks = @(
    @{ Test = { (Test-Tool -Cmd "nmap" -Arg "--version" -Regex "Nmap version") -ne $null }; Msg = "Nmap works (needed for Phase 1.2)" }
    @{ Test = { (Test-Tool -Cmd "git"  -Arg "--version" -Regex "git version") -ne $null };  Msg = "Git works (optional)" }
)

$allPassed = $true
foreach ($check in $checks) {
    if (& $check.Test) {
        Write-Success $check.Msg
    }
    else {
        Write-Err "Failed: $($check.Msg)"
        $allPassed = $false
    }
}
foreach ($check in $optionalChecks) {
    if (& $check.Test) {
        Write-Success $check.Msg
    }
    else {
        Write-Warn "Optional missing: $($check.Msg)"
    }
}

# ----------------------------------------------------------------
# Final message
# ----------------------------------------------------------------
Write-Host "`n============================================================" -ForegroundColor Magenta

if ($allPassed) {
    Write-Host @"
   Setup complete! Project is ready to run.

   To start:
     - Double-click run.bat (will request admin)
     - Browser will open at http://127.0.0.1:5173
"@ -ForegroundColor Green

    if ($LogFile -ne "") { try { Stop-Transcript | Out-Null } catch {} }
    exit 0
}
else {
    Write-Host @"
   Setup completed with errors. Review messages above.
   Log file: $LogFile

   Tip: if Python or Node was JUST installed, close this window,
   open a new terminal, and re-run setup.bat.
"@ -ForegroundColor Yellow

    if ($LogFile -ne "") { try { Stop-Transcript | Out-Null } catch {} }
    exit 1
}
