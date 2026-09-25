<#
.SYNOPSIS
  Personal patches for Photon Studio (per-user install) that survive official updates.
.DESCRIPTION
  apply    Back up the stock app.asar once per version, then write the patched archive.
  verify   Report which patches are present in the installed app.asar (exit 1 if any is missing).
  restore  Put the stock app.asar of the installed version back.
  update   Ask tenzen.studio for the latest Windows build, install it silently, then apply.
           -Reinstall installs the current version again (update round-trip test).
           -Installer FILE installs a downloaded installer instead (no network access).
#>
[CmdletBinding()]
param(
    [Parameter(Position = 0, Mandatory)][ValidateSet('apply', 'verify', 'restore', 'update')][string]$Command,
    [switch]$Reinstall,
    [string]$Installer
)
$ErrorActionPreference = 'Stop'

$Install = Join-Path $env:LOCALAPPDATA 'Programs\Photon Studio'
$Exe = Join-Path $Install 'Photon Studio.exe'
$Asar = Join-Path $Install 'resources\app.asar'
$Home_ = Join-Path $env:LOCALAPPDATA 'photon-mod'
$Backup = Join-Path $Home_ 'backup'
$Patches = @(Get-ChildItem (Join-Path $PSScriptRoot 'patches') -Filter *.json | Sort-Object Name | ForEach-Object FullName)
$AsarPy = Join-Path $PSScriptRoot 'asar.py'
$DownloadApi = 'https://tenzen.studio/api/v1/photon/download?platform=win32&arch=x64'

function Invoke-Asar([string[]]$Arguments) {
    $py = if (Get-Command python -ErrorAction SilentlyContinue) { 'python' } elseif (Get-Command py -ErrorAction SilentlyContinue) { 'py' } else { throw 'Python 3 is required (python or py on PATH).' }
    $out = & $py $AsarPy @Arguments
    $code = $LASTEXITCODE
    [pscustomobject]@{ Code = $code; Json = ($out | Out-String | ConvertFrom-Json) }
}

function Get-InstalledVersion {
    if (-not (Test-Path $Exe)) { throw "Photon Studio is not installed at $Install" }
    (Get-Item $Exe).VersionInfo.FileVersion
}

function Assert-NotRunning {
    $running = Get-Process -ErrorAction SilentlyContinue | Where-Object { $_.Path -and $_.Path.StartsWith($Install, [StringComparison]::OrdinalIgnoreCase) }
    if ($running) { throw "Photon Studio is running (PID $($running.Id -join ', ')). Close it first." }
}

function Get-PatchState([string]$Path) {
    $r = Invoke-Asar (@('check', $Path) + $Patches)
    if ($r.Code -ne 0) { throw "asar check failed: $($r.Json.error)" }
    $r.Json
}

function Invoke-Apply {
    Assert-NotRunning
    $version = Get-InstalledVersion
    $stock = Join-Path $Backup "app.asar.orig-$version"
    New-Item -ItemType Directory -Force $Backup | Out-Null
    if (-not (Test-Path $stock)) {
        $state = Get-PatchState $Asar
        if ($state.PSObject.Properties.Value -contains $true) { throw "Installed app.asar is already patched but no stock backup exists for $version. Reinstall Photon, then run apply." }
        Copy-Item $Asar $stock
        Write-Host "Backed up stock app.asar for $version"
    }
    $staged = "$Asar.photon-mod"
    $r = Invoke-Asar (@('apply', $stock, $staged) + $Patches)
    if ($r.Code -ne 0) { throw "Patching $version failed, app left unchanged: $($r.Json.error)" }
    $state = Get-PatchState $staged
    if ($state.PSObject.Properties.Value -contains $false) { Remove-Item $staged; throw "Staged archive is missing patches: $($state | ConvertTo-Json -Compress)" }
    Move-Item $staged $Asar -Force
    Get-ChildItem $Backup -Filter 'app.asar.orig-*' | Sort-Object LastWriteTime -Descending | Select-Object -Skip 2 | Remove-Item
    Write-Host "Applied $($Patches.Count) patches to Photon Studio $version"
}

function Invoke-Verify {
    $state = Get-PatchState $Asar
    $state.PSObject.Properties | ForEach-Object { '{0,-6} {1}' -f ($(if ($_.Value) { 'OK' } else { 'MISS' })), $_.Name }
    if ($state.PSObject.Properties.Value -contains $false) { exit 1 }
}

function Invoke-Restore {
    Assert-NotRunning
    $version = Get-InstalledVersion
    $stock = Join-Path $Backup "app.asar.orig-$version"
    if (-not (Test-Path $stock)) { throw "No stock backup for $version in $Backup" }
    Copy-Item $stock $Asar -Force
    Write-Host "Restored stock app.asar for $version"
}

function Get-LatestRelease {
    Add-Type -AssemblyName System.Net.Http
    $handler = [System.Net.Http.HttpClientHandler]::new(); $handler.AllowAutoRedirect = $false
    $client = [System.Net.Http.HttpClient]::new($handler)
    try { $response = $client.GetAsync($DownloadApi).GetAwaiter().GetResult() } finally { $client.Dispose() }
    $location = $response.Headers.Location
    if ([int]$response.StatusCode -ne 302 -or -not $location) { throw "Unexpected answer from download API: $([int]$response.StatusCode)" }
    $url = $location.AbsoluteUri
    if ($url -notmatch '^https://downloads\.tenzen\.studio/photon/stable/win32/(\d+\.\d+\.\d+)/Photon-Studio-\1-win-x64\.exe$') { throw "Unexpected download URL: $url" }
    [pscustomobject]@{ Version = $Matches[1]; Url = $url }
}

function Invoke-Update {
    if ($Installer) {
        if (-not (Test-Path $Installer)) { throw "Installer not found: $Installer" }
        $file = (Resolve-Path $Installer).Path
    } else {
        $installed = Get-InstalledVersion
        $latest = Get-LatestRelease
        Write-Host "Installed $installed, latest $($latest.Version)"
        if (-not $Reinstall -and [version]$latest.Version -le [version]$installed) { Write-Host 'Up to date.'; return }
        $file = Join-Path $env:TEMP (Split-Path $latest.Url -Leaf)
    }
    Assert-NotRunning
    if (-not $Installer) { Invoke-WebRequest $latest.Url -OutFile $file -UseBasicParsing }
    Write-Host "Installing $(Split-Path $file -Leaf) silently"
    $p = Start-Process $file -ArgumentList '/S' -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "Installer exited with $($p.ExitCode)" }
    if (-not $Installer) { Remove-Item $file }
    Invoke-Apply
}

switch ($Command) {
    'apply' { Invoke-Apply }
    'verify' { Invoke-Verify }
    'restore' { Invoke-Restore }
    'update' { Invoke-Update }
}
