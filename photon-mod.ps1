<#
.SYNOPSIS
  Personal patches for Photon Studio (per-user install) that survive official updates.
.DESCRIPTION
  apply    Back up the stock app.asar and exe once per version, write the patched archive,
           set the Electron fuses from fuses.json.
  verify   Report patch and fuse state of the installed app (exit 1 if anything is missing).
  restore  Put the stock app.asar and exe of the installed version back.
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
$FusesPy = Join-Path $PSScriptRoot 'fuses.py'
$FuseConfig = Get-Content (Join-Path $PSScriptRoot 'fuses.json') -Raw | ConvertFrom-Json
$DownloadApi = 'https://tenzen.studio/api/v1/photon/download?platform=win32&arch=x64'

function Invoke-Py([string]$Script, [string[]]$Arguments) {
    $py = if (Get-Command python -ErrorAction SilentlyContinue) { 'python' } elseif (Get-Command py -ErrorAction SilentlyContinue) { 'py' } else { throw 'Python 3 is required (python or py on PATH).' }
    $out = & $py $Script @Arguments
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
    $r = Invoke-Py $AsarPy (@('check', $Path) + $Patches)
    if ($r.Code -ne 0) { throw "asar check failed: $($r.Json.error)" }
    $r.Json
}

function Test-Hardened([string]$Path) {
    $r = Invoke-Py $FusesPy @('read', $Path)
    if ($r.Code -ne 0) { throw "fuse read failed: $($r.Json.error)" }
    $bad = @($FuseConfig.PSObject.Properties | Where-Object { $r.Json.fuses.($_.Name) -ne $_.Value } | ForEach-Object Name)
    [pscustomobject]@{ Ok = $bad.Count -eq 0; Wire = $r.Json.wire; Differs = $bad }
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
    $r = Invoke-Py $AsarPy (@('apply', $stock, $staged) + $Patches)
    if ($r.Code -ne 0) { throw "Patching $version failed, app left unchanged: $($r.Json.error)" }
    $state = Get-PatchState $staged
    if ($state.PSObject.Properties.Value -contains $false) { Remove-Item $staged; throw "Staged archive is missing patches: $($state | ConvertTo-Json -Compress)" }
    Move-Item $staged $Asar -Force
    $stockExe = Join-Path $Backup "Photon Studio.exe.orig-$version"
    if (-not (Test-Path $stockExe)) {
        if ((Test-Hardened $Exe).Ok) { throw "Installed exe already has the fuse config but no stock backup exists for $version. Reinstall Photon, then run apply." }
        Copy-Item $Exe $stockExe
        Write-Host "Backed up stock exe for $version"
    }
    $r = Invoke-Py $FusesPy @('apply', $Exe)
    if ($r.Code -ne 0) { throw "Setting fuses failed: $($r.Json.error)" }
    foreach ($pattern in 'app.asar.orig-*', 'Photon Studio.exe.orig-*') {
        Get-ChildItem $Backup -Filter $pattern | Sort-Object LastWriteTime -Descending | Select-Object -Skip 2 | Remove-Item
    }
    Write-Host "Applied $($Patches.Count) patches and fuse wire $($r.Json.wire) to Photon Studio $version"
}

function Invoke-Verify {
    $state = Get-PatchState $Asar
    $state.PSObject.Properties | ForEach-Object { '{0,-6} {1}' -f ($(if ($_.Value) { 'OK' } else { 'MISS' })), $_.Name }
    $fuses = Test-Hardened $Exe
    '{0,-6} fuses {1}{2}' -f ($(if ($fuses.Ok) { 'OK' } else { 'MISS' })), $fuses.Wire, ($(if ($fuses.Ok) { '' } else { " (differs: $($fuses.Differs -join ', '))" }))
    if ($state.PSObject.Properties.Value -contains $false -or -not $fuses.Ok) { exit 1 }
}

function Invoke-Restore {
    Assert-NotRunning
    $version = Get-InstalledVersion
    $stock = Join-Path $Backup "app.asar.orig-$version"
    if (-not (Test-Path $stock)) { throw "No stock backup for $version in $Backup" }
    Copy-Item $stock $Asar -Force
    $stockExe = Join-Path $Backup "Photon Studio.exe.orig-$version"
    if (Test-Path $stockExe) { Copy-Item $stockExe $Exe -Force }
    Write-Host "Restored stock app.asar$(if (Test-Path $stockExe) { ' and exe' }) for $version"
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
