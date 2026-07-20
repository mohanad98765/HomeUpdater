<#
.SYNOPSIS
    Sign HomeUpdater's executable(s) with an Authenticode code-signing certificate.

.DESCRIPTION
    Signs the app exe and/or the installer with SHA-256 plus an RFC-3161 timestamp.

    By default it uses a self-signed development certificate kept in the current
    user's personal store (Cert:\CurrentUser\My). A self-signed signature proves
    the file has not been tampered with and lets THIS machine trust the publisher
    once the certificate is imported (see SIGNING.md). It will NOT satisfy
    Microsoft Smart App Control / SmartScreen for distribution to other machines.
    For that you need a certificate from a public CA (OV, or EV for instant SAC
    trust). When you have one, pass -Thumbprint or -PfxPath and the same pipeline
    signs with it, no other change needed.

.PARAMETER Files
    Files to sign. Defaults to the built app exe plus the installer if they exist.

.PARAMETER CreateCert
    Create the self-signed dev certificate if it does not exist yet.

.PARAMETER ExportCert
    Export the public certificate (.cer) so it can be trusted on this machine.

.PARAMETER Thumbprint
    Use an existing certificate (in any My store) by thumbprint, e.g. a real
    OV/EV cert, instead of the self-signed dev cert.

.PARAMETER PfxPath / PfxPassword
    Sign using a .pfx file (real CA certificate) instead of the store.

.EXAMPLE
    # First time: create the dev cert, export it, and sign both artifacts
    .\sign.ps1 -CreateCert -ExportCert

.EXAMPLE
    # Later, with a real purchased certificate
    .\sign.ps1 -PfxPath C:\certs\homeupdater.pfx -PfxPassword (Read-Host -AsSecureString)
#>
[CmdletBinding()]
param(
    [string[]]$Files,
    [string]$Subject = "HomeUpdater Dev (Self-Signed)",
    [string]$Thumbprint,
    [string]$PfxPath,
    [System.Security.SecureString]$PfxPassword,
    [switch]$CreateCert,
    [switch]$ExportCert,
    [string]$ExportPath,
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)

$ErrorActionPreference = "Stop"

function Write-Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Write-Ok($m)   { Write-Host "    $m" -ForegroundColor Green }
function Write-Note($m) { Write-Host "    $m" -ForegroundColor Yellow }

# ----------------------------------------------------------- resolve files
if (-not $Files -or $Files.Count -eq 0) {
    $candidates = @(
        (Join-Path $PSScriptRoot "..\backend\dist\HomeUpdater\HomeUpdater.exe"),
        (Get-ChildItem (Join-Path $PSScriptRoot "Output\HomeUpdater-Setup-*.exe") -ErrorAction SilentlyContinue |
            Select-Object -First 1 -ExpandProperty FullName)
    )
    $Files = $candidates | Where-Object { Test-Path $_ } | ForEach-Object { (Resolve-Path $_).Path }
    if ($Files.Count -eq 0) {
        throw "No files to sign. Build the exe/installer first (see BUILD.md), or pass -Files."
    }
}

# ----------------------------------------------------------- resolve certificate
$cert = $null

if ($PfxPath) {
    Write-Step "Loading certificate from PFX: $PfxPath"
    if (-not (Test-Path $PfxPath)) { throw "PFX not found: $PfxPath" }
    if (-not $PfxPassword) { $PfxPassword = Read-Host "PFX password" -AsSecureString }
    $cert = Get-PfxCertificate -FilePath $PfxPath -Password $PfxPassword
}
elseif ($Thumbprint) {
    Write-Step "Locating certificate by thumbprint: $Thumbprint"
    $cert = Get-ChildItem -Path Cert:\CurrentUser\My, Cert:\LocalMachine\My |
        Where-Object { $_.Thumbprint -eq $Thumbprint } | Select-Object -First 1
    if (-not $cert) { throw "No certificate with thumbprint $Thumbprint in My stores." }
}
else {
    Write-Step "Looking for self-signed dev cert: CN=$Subject"
    # Match by subject + Code Signing EKU OID (1.3.6.1.5.5.7.3.3) so it is
    # locale-independent (FriendlyName is localized on non-English Windows).
    $cert = Get-ChildItem Cert:\CurrentUser\My |
        Where-Object {
            $_.Subject -like "*CN=$Subject*" -and $_.HasPrivateKey -and
            ($_.EnhancedKeyUsageList | Where-Object { $_.ObjectId -eq "1.3.6.1.5.5.7.3.3" })
        } | Sort-Object NotAfter -Descending | Select-Object -First 1

    if (-not $cert) {
        if (-not $CreateCert) {
            throw "No self-signed dev cert found. Re-run with -CreateCert to make one."
        }
        Write-Step "Creating self-signed code-signing certificate (valid 5 years)"
        $cert = New-SelfSignedCertificate `
            -Type CodeSigningCert `
            -Subject "CN=$Subject, O=HomeUpdater" `
            -FriendlyName "HomeUpdater Code Signing (Self-Signed)" `
            -KeyUsage DigitalSignature `
            -KeyExportPolicy Exportable `
            -HashAlgorithm SHA256 `
            -CertStoreLocation Cert:\CurrentUser\My `
            -NotAfter (Get-Date).AddYears(5)
        Write-Ok "Created. Thumbprint: $($cert.Thumbprint)"
    }
}

Write-Ok "Using: $($cert.Subject)  [$($cert.Thumbprint)]"

# ----------------------------------------------------------- export public cert
if ($ExportCert) {
    if (-not $ExportPath) { $ExportPath = Join-Path $PSScriptRoot "assets\HomeUpdater-CodeSign.cer" }
    Write-Step "Exporting public certificate to $ExportPath"
    $dir = Split-Path $ExportPath -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Force -Path $dir | Out-Null }
    Export-Certificate -Cert $cert -FilePath $ExportPath -Type CERT | Out-Null
    Write-Ok "Exported. Import it (see SIGNING.md) to trust this publisher on this PC."
}

# ----------------------------------------------------------- locate signtool (preferred)
function Find-SignTool {
    $onPath = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($onPath) { return $onPath.Source }
    $roots = @("${env:ProgramFiles(x86)}\Windows Kits\10\bin", "$env:ProgramFiles\Windows Kits\10\bin")
    foreach ($r in $roots) {
        if (Test-Path $r) {
            $st = Get-ChildItem -Path $r -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -match "\\x64\\" } |
                Sort-Object FullName -Descending | Select-Object -First 1
            if ($st) { return $st.FullName }
        }
    }
    return $null
}
$signtool = Find-SignTool

# ----------------------------------------------------------- sign each file
foreach ($f in $Files) {
    Write-Step "Signing: $f"
    if ($signtool) {
        & $signtool sign /fd SHA256 /td SHA256 /tr $TimestampUrl /sha1 $cert.Thumbprint "$f"
        if ($LASTEXITCODE -ne 0) { throw "signtool failed for $f (exit $LASTEXITCODE)" }
    }
    else {
        Write-Note "signtool not found, falling back to Set-AuthenticodeSignature"
        $res = Set-AuthenticodeSignature -FilePath $f -Certificate $cert `
            -HashAlgorithm SHA256 -TimestampServer $TimestampUrl
        Write-Note "Signature status: $($res.Status)"
    }

    $sig = Get-AuthenticodeSignature -FilePath $f
    Write-Ok "Status: $($sig.Status)  Signer: $($sig.SignerCertificate.Subject)"
}

Write-Step "Done. Signed $($Files.Count) file(s)."
Write-Note "A self-signed signature is trusted only where its certificate is imported."
Write-Note "For distribution / Smart App Control, sign with a CA-issued (OV/EV) certificate."
