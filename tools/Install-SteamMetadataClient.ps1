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
. (Join-Path $PSScriptRoot 'SteamMetadataClient.Install.ps1')
Install-SteamMetadataClient -WikiRoot (Split-Path -Parent $PSScriptRoot) `
    -Url 'https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip' `
    -DownloadTimeoutSec 60 -DownloadDeadlineSec 120 -BootstrapDeadlineSec 600 `
    -Download {
        param($Url, $Archive, $TimeoutSec)
        Microsoft.PowerShell.Utility\Invoke-WebRequest -Uri $Url -OutFile $Archive -TimeoutSec $TimeoutSec
    } -SignatureCheck {
        param($Client)
        Microsoft.PowerShell.Security\Get-AuthenticodeSignature -LiteralPath $Client
    }
