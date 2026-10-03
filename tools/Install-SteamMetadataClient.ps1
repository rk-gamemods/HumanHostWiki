#Requires -Version 7
<#
.SYNOPSIS
    Installs an isolated signed SteamCMD client for public build metadata.
.DESCRIPTION
    Uses Valve's Windows bootstrap package. Does not log into an account or
    download game depots. Machine paths stay in .local/steamcmd.json.
#>
[CmdletBinding()]
param()
$ErrorActionPreference = 'Stop'
$wikiRoot = Split-Path -Parent $PSScriptRoot
$toolRoot = Join-Path $wikiRoot '.local\tools\steamcmd'
$client = Join-Path $toolRoot 'steamcmd.exe'
if (-not (Test-Path -LiteralPath $client)) {
    if (Test-Path -LiteralPath $toolRoot) {
        throw "Existing tool directory has no client. Inspect it before retrying: $toolRoot"
    }
    New-Item -ItemType Directory -Path $toolRoot | Out-Null
    $archive = Join-Path $toolRoot 'steamcmd.zip'
    Invoke-WebRequest -Uri 'https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip' -OutFile $archive
    Expand-Archive -LiteralPath $archive -DestinationPath $toolRoot
}
function Assert-ValveClient {
    $signature = Get-AuthenticodeSignature -LiteralPath $client
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch '(^|, )O=Valve( Corp\.)?(,|$)') {
        throw "SteamCMD must have a valid Valve signature: $client"
    }
}
Assert-ValveClient
# The first bootstrap may update itself and exit 1. Confirm the installed
# client on a second invocation, rather than accepting a failed exit as success.
Push-Location -LiteralPath $toolRoot
try {
    & $client +quit
    if ($LASTEXITCODE -ne 0) {
        Assert-ValveClient
        & $client +quit
    }
    if ($LASTEXITCODE -ne 0) { throw "SteamCMD setup failed with exit $LASTEXITCODE" }
} finally { Pop-Location }
Assert-ValveClient
$settings = Join-Path $wikiRoot '.local\steamcmd.json'
$payload = @{ executable = $client } | ConvertTo-Json
if (Test-Path -LiteralPath $settings) {
    $existing = Get-Content -Raw -LiteralPath $settings | ConvertFrom-Json
    if ($existing.executable -ne $client) { throw "Preserving different configured metadata client: $settings" }
} else {
    [System.IO.File]::WriteAllText($settings, $payload + "`n", [System.Text.UTF8Encoding]::new($false))
}
Write-Output "Steam metadata client ready: $client"
