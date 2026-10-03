#Requires -Version 7
<#
.SYNOPSIS
    Installs an isolated signed SteamCMD client for public build metadata.
.DESCRIPTION
    Uses Valve's Windows bootstrap package. Does not log into an account or
    download game depots. Machine paths stay in .local/steamcmd.json.
#>
[CmdletBinding()]
param([Parameter(DontShow)][hashtable]$TestOptions = @{})
$ErrorActionPreference = 'Stop'
$wikiRoot = Split-Path -Parent $PSScriptRoot
$options = @{
    ToolRoot = Join-Path $wikiRoot '.local\tools\steamcmd'
    Url = 'https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip'
    DownloadTimeoutSec = 60
    DownloadDeadlineSec = 120
    BootstrapDeadlineSec = 600
    Download = { param($Url, $Archive, $TimeoutSec) Invoke-WebRequest -Uri $Url -OutFile $Archive -TimeoutSec $TimeoutSec }
    SignatureCheck = { param($Client) Get-AuthenticodeSignature -LiteralPath $Client }
}
foreach ($key in $TestOptions.Keys) {
    if (-not $options.ContainsKey($key)) { throw "Unknown test option: $key" }
    $options[$key] = $TestOptions[$key]
}
foreach ($key in 'DownloadTimeoutSec', 'DownloadDeadlineSec', 'BootstrapDeadlineSec') {
    if ($options[$key] -le 0 -or $options[$key] -gt 2147483) { throw "Invalid deadline: $key" }
}
$toolRoot = [System.IO.Path]::GetFullPath($options.ToolRoot)
$toolsRoot = Split-Path -Parent $toolRoot
$markerName = '.install-complete'
$refusal = "Existing tool directory has no client. Inspect it before retrying: $toolRoot"

function Invoke-BoundedProcess([string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory, [int]$DeadlineSec, [string]$Name) {
    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -PassThru -NoNewWindow
    try {
        if (-not $process.WaitForExit($DeadlineSec * 1000)) {
            $process.Kill($true)
            $process.WaitForExit()
            throw "$Name exceeded its $DeadlineSec second deadline."
        }
        return $process.ExitCode
    } finally {
        # Also stop an owned child if waiting was interrupted by an exception.
        if (-not $process.HasExited) {
            $process.Kill($true)
            $process.WaitForExit()
        }
        $process.Dispose()
    }
}

function Assert-InstallTree([string]$Path) {
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if ((Split-Path -Parent $fullPath) -ne $toolsRoot) { throw "Install cleanup escaped tool parent: $Path" }
    $entries = @(Get-Item -LiteralPath $fullPath) + @(Get-ChildItem -LiteralPath $fullPath -Recurse -Force)
    if ($entries | Where-Object { $_.Attributes -band [System.IO.FileAttributes]::ReparsePoint }) { throw $refusal }
}

function Test-InterruptedInstall {
    Assert-InstallTree $toolRoot
    if (-not (Get-Item -LiteralPath $toolRoot).PSIsContainer) { return $false }
    # Conservative allowlist: unknown files, including those in known folders,
    # require inspection instead of being discarded during recovery.
    $rootFiles = '^(steamcmd\.(exe(\.old|\.tmp)?|zip)|steam(errorreporter(64)?|service)\.exe|steam(client(64)?|console)?\.dll|tier0_s(64)?\.dll|vstdlib_s(64)?\.dll|crashhandler(64)?\.dll|dbghelp\.dll)$'
    foreach ($entry in Get-ChildItem -LiteralPath $toolRoot -Recurse -Force) {
        $relative = [System.IO.Path]::GetRelativePath($toolRoot, $entry.FullName).Replace('\', '/')
        if ($entry.PSIsContainer) {
            if ($relative -notmatch '^(package|logs|public|dumps|config|appcache|bin)$') { return $false }
        } elseif ($relative -notmatch $rootFiles -and
            $relative -notmatch '^package/(steam_cmd_win32(\.manifest(\.tmp)?)?|steamcmd_(bins_win32|public_all)\.zip(\.[a-f0-9]+)?(\.vz|\.zip|\.installed)?)$' -and
            $relative -notmatch '^logs/(bootstrap_log|content_log|connection_log|console_log|stderr)\.(txt|log)(\.old)?$' -and
            $relative -notmatch '^public/steambootstrapper_[a-z]+\.txt$' -and
            $relative -notmatch '^config/(config|SteamAppData|DialogConfig)\.vdf$' -and
            $relative -notmatch '^appcache/(appinfo|packageinfo)\.vdf$' -and
            $relative -notmatch '^bin/(steamservice|steamerrorreporter(64)?)\.exe$' -and
            $relative -notmatch '^dumps/(assert|crash)_steamcmd[^/]*\.dmp$') { return $false }
    }
    return $true
}

function Assert-ValveClient {
    $signature = & $options.SignatureCheck $client
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch '(^|, )O=Valve( Corp\.)?(,|$)') {
        throw "SteamCMD must have a valid Valve signature: $client"
    }
}
$staging = $null
if (-not (Test-Path -LiteralPath $toolsRoot)) { New-Item -ItemType Directory -Path $toolsRoot | Out-Null }
# Staging names are reserved for this installer; never traverse linked trees.
foreach ($leftover in Get-ChildItem -LiteralPath $toolsRoot -Directory -Filter 'steamcmd.staging-*') {
    Assert-InstallTree $leftover.FullName
    Remove-Item -LiteralPath $leftover.FullName -Recurse
}
if (Test-Path -LiteralPath $toolRoot) {
    Assert-InstallTree $toolRoot
    if (-not (Test-Path -LiteralPath (Join-Path $toolRoot $markerName) -PathType Leaf)) {
        if (-not (Test-InterruptedInstall)) { throw $refusal }
        Remove-Item -LiteralPath $toolRoot -Recurse
    } elseif (-not (Test-Path -LiteralPath (Join-Path $toolRoot 'steamcmd.exe') -PathType Leaf)) { throw $refusal }
}
try {
    $installRoot = $toolRoot
    if (-not (Test-Path -LiteralPath $toolRoot)) {
        $staging = Join-Path $toolsRoot ('steamcmd.staging-' + [guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $staging | Out-Null
        $archive = Join-Path $staging 'steamcmd.zip'
        # An isolated PowerShell process supplies an overall bound even when
        # request retries/DNS outlast Invoke-WebRequest's per-request timeout.
        $downloadArgs = (@($options.Url, $archive, $options.DownloadTimeoutSec) | ForEach-Object { "'" + "$_".Replace("'", "''") + "'" }) -join ' '
        $downloadCode = '$ErrorActionPreference = ''Stop''; $ProgressPreference = ''SilentlyContinue''; & {' + $options.Download.ToString() + '} ' + $downloadArgs
        $encoded = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($downloadCode))
        $exitCode = Invoke-BoundedProcess (Join-Path $PSHOME 'pwsh.exe') @('-NoProfile', '-EncodedCommand', $encoded) $staging $options.DownloadDeadlineSec 'SteamCMD download'
        if ($exitCode -ne 0) { throw "SteamCMD download failed with exit $exitCode" }
        try { Expand-Archive -LiteralPath $archive -DestinationPath $staging -ErrorAction Stop }
        catch { throw "SteamCMD archive expansion failed: $($_.Exception.Message)" }
        $installRoot = $staging
    }
    $client = Join-Path $installRoot 'steamcmd.exe'
    if (-not (Test-Path -LiteralPath $client -PathType Leaf)) { throw "SteamCMD archive has no client: $client" }
    Assert-ValveClient
    # The first bootstrap may update itself and exit 1. Confirm on a second
    # invocation rather than accepting a failed exit as success.
    $exitCode = Invoke-BoundedProcess $client @('+quit') $installRoot $options.BootstrapDeadlineSec 'SteamCMD bootstrap'
    if ($exitCode -ne 0) {
        Assert-ValveClient
        $exitCode = Invoke-BoundedProcess $client @('+quit') $installRoot $options.BootstrapDeadlineSec 'SteamCMD bootstrap confirmation'
    }
    if ($exitCode -ne 0) { throw "SteamCMD setup failed with exit $exitCode" }
    Assert-ValveClient
    if ($staging) {
        [System.IO.Directory]::Move($staging, $toolRoot)
        [System.IO.File]::WriteAllText((Join-Path $toolRoot $markerName), "SteamCMD installer complete`n")
    }
} finally {
    if ($staging -and (Test-Path -LiteralPath $staging)) {
        Assert-InstallTree $staging
        Remove-Item -LiteralPath $staging -Recurse
    }
}
$client = Join-Path $toolRoot 'steamcmd.exe'
$settings = Join-Path (Split-Path -Parent $toolsRoot) 'steamcmd.json'
$payload = @{ executable = $client } | ConvertTo-Json
if (Test-Path -LiteralPath $settings) {
    $existing = Get-Content -Raw -LiteralPath $settings | ConvertFrom-Json
    if ($existing.executable -ne $client) { throw "Preserving different configured metadata client: $settings" }
} else {
    [System.IO.File]::WriteAllText($settings, $payload + "`n", [System.Text.UTF8Encoding]::new($false))
}
Write-Output "Steam metadata client ready: $client"
