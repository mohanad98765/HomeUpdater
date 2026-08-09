# HomeUpdater network diagnostic - collect the facts a scan depends on.
#
# ASCII only, and every message is English on purpose: Windows PowerShell 5.1 reads a
# BOM-less UTF-8 script as ANSI, so an Arabic line here would be a parse error on the
# tester's machine and the window would close before writing anything.
#
# Read-only. It changes nothing: no settings, no processes, no files outside the report.
# It answers four questions that decide whether a scan can work at all:
#   1. which adapter owns the route, and what subnet the app will therefore scan
#   2. how wide the real subnet is (the scan silently narrows to a /24 past 1022 hosts)
#   3. whether a VPN/tunnel is holding the default route (the scan then covers 1 address)
#   4. how many neighbours the OS itself can see (the ceiling for any scanner)

$ErrorActionPreference = "SilentlyContinue"
$out = Join-Path ([Environment]::GetFolderPath("Desktop")) "HomeUpdater-network-report.txt"
$lines = New-Object System.Collections.Generic.List[string]
function W([string]$s) { $lines.Add($s) | Out-Null; Write-Host $s }

W "HomeUpdater network diagnostic"
W ("generated: " + (Get-Date -Format "yyyy-MM-dd HH:mm:ss"))
W ("computer:  " + $env:COMPUTERNAME)
W ""

W "== 1. adapters with an IPv4 address =="
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.IPAddress -ne "127.0.0.1" } | ForEach-Object {
    # Hidden/filter adapters have an IP but no MSFT_NetAdapter object; asking for one
    # prints a red error that makes a healthy machine look broken to whoever runs this.
    $ifc = Get-NetAdapter -InterfaceIndex $_.InterfaceIndex -ErrorAction SilentlyContinue
    $st = if ($ifc) { $ifc.Status } else { "hidden" }
    $ty = if ($ifc) { $ifc.InterfaceType } else { "-" }
    W ("  {0,-28} {1,-16} /{2,-3} status={3} type={4}" -f `
        $_.InterfaceAlias, $_.IPAddress, $_.PrefixLength, $st, $ty)
}
W ""

W "== 2. default route (this decides which network the app scans) =="
$best = Get-NetRoute -DestinationPrefix "0.0.0.0/0" | Sort-Object RouteMetric, ifMetric | Select-Object -First 1
if ($best) {
    $src = Get-NetIPAddress -InterfaceIndex $best.ifIndex -AddressFamily IPv4 | Select-Object -First 1
    $alias = (Get-NetAdapter -InterfaceIndex $best.ifIndex).InterfaceAlias
    W ("  via {0} on '{1}'" -f $best.NextHop, $alias)
    if ($src) {
        W ("  the app will scan around: {0}/{1}" -f $src.IPAddress, $src.PrefixLength)
        $usable = [math]::Pow(2, 32 - $src.PrefixLength) - 2
        W ("  addresses in that subnet: {0}" -f $usable)
        if ($src.PrefixLength -ge 31) {
            W "  VERDICT: this is a tunnel-style address. The scan would cover ONE address."
        } elseif ($usable -gt 1022) {
            W "  VERDICT: wider than the app sweeps. It will narrow to 254 addresses and skip the rest."
        } else {
            W "  VERDICT: the whole subnet is within what the app sweeps."
        }
    }
} else { W "  NO DEFAULT ROUTE FOUND" }
W ""

W "== 3. VPN / tunnel software holding the route? =="
$tun = Get-NetAdapter | Where-Object { $_.Status -eq "Up" -and (
    $_.InterfaceType -in 23, 131 -or
    $_.InterfaceDescription -match "VPN|AnyConnect|GlobalProtect|Zscaler|Netskope|WireGuard|Tailscale|OpenVPN|Wintun|TAP-Windows|Forticlient|Pulse|Ivanti") }
if ($tun) { $tun | ForEach-Object { W ("  UP: {0} | {1}" -f $_.InterfaceAlias, $_.InterfaceDescription) } }
else { W "  none detected" }
W ""

W "== 4. neighbours the operating system can see =="
$nb = Get-NetNeighbor -AddressFamily IPv4 | Where-Object {
    $_.State -in "Reachable", "Stale", "Delay", "Probe" -and
    $_.LinkLayerAddress -and $_.LinkLayerAddress -ne "00-00-00-00-00-00" -and
    $_.IPAddress -notmatch "^(224\.|239\.|255\.)" }
W ("  reachable neighbours: {0}" -f @($nb).Count)
$nb | Sort-Object { [version](($_.IPAddress -replace '\.','.')) } -ErrorAction SilentlyContinue | ForEach-Object {
    W ("    {0,-16} {1}" -f $_.IPAddress, $_.LinkLayerAddress)
}
$byMac = $nb | Group-Object LinkLayerAddress | Where-Object { $_.Count -gt 1 }
if ($byMac) {
    W ""
    W "  NOTE - several addresses answer with the SAME hardware address."
    W "  That means those devices are reached through a router, not directly."
    $byMac | ForEach-Object { W ("    {0} <- {1} addresses" -f $_.Name, $_.Count) }
}
W ""

W "== 5. is the app installed, and which version? =="
$v = "C:\Program Files\HomeUpdater\_internal\VERSION"
if (Test-Path $v) { W ("  version: " + (Get-Content $v -Raw).Trim()) } else { W "  not installed at the default path" }
W ""
W "== end =="

$lines | Out-File -FilePath $out -Encoding utf8
Write-Host ""
Write-Host "Report saved to: $out"
Write-Host "Please send that file back."
