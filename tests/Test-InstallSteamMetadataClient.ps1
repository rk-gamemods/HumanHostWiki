#Requires -Version 7
<# Offline tests of the real installer using a local archive and a small client exe. #>
$ErrorActionPreference = 'Stop'
$installer = Join-Path (Split-Path -Parent $PSScriptRoot) 'tools/Install-SteamMetadataClient.ps1'
$fixture = Join-Path ([System.IO.Path]::GetTempPath()) ('steamcmd-test-' + [guid]::NewGuid().ToString('N'))
$previousFixture = $env:WIKI_STEAMCMD_FIXTURE
$cases = 0
$ownedProcesses = [System.Collections.Generic.List[System.Diagnostics.Process]]::new()

function Assert-True([bool]$Value, [string]$Message) {
    if (-not $Value) { throw $Message }
}
function New-Case([string]$Mode = 'success') {
    $script:caseRoot = Join-Path $fixture ([guid]::NewGuid().ToString('N') + ' case')
    New-Item -ItemType Directory -Path $caseRoot | Out-Null
    $env:WIKI_STEAMCMD_FIXTURE = $caseRoot
    Set-Content -LiteralPath (Join-Path $caseRoot 'mode.txt') -Value $Mode
    $script:toolRoot = Join-Path $caseRoot '.local/tools/steamcmd'
    $script:options = @{
        ToolRoot = $toolRoot
        Url = $archive
        DownloadTimeoutSec = 2
        DownloadDeadlineSec = 10
        BootstrapDeadlineSec = 3
        Download = {
            param($Url, $Archive, $TimeoutSec)
            if ($TimeoutSec -ne 2) { throw 'Request timeout was not forwarded.' }
            Add-Content -LiteralPath (Join-Path $env:WIKI_STEAMCMD_FIXTURE 'downloads.txt') -Value 'download'
            Copy-Item -LiteralPath $Url -Destination $Archive
        }
        SignatureCheck = {
            param($Client)
            if (-not (Test-Path -LiteralPath $Client -PathType Leaf)) { throw 'Signature check received no client.' }
            @{ Status = 'Valid'; SignerCertificate = @{ Subject = 'CN=Valve Corp., O=Valve Corp., C=US' } }
        }
    }
}
function Run-Installer([string]$ExpectedError = '') {
    $caught = ''
    try { & $installer -TestOptions $options | Out-Null } catch { $caught = $_.Exception.Message }
    if ($ExpectedError) { Assert-True ($caught.Contains($ExpectedError)) "Expected '$ExpectedError', got '$caught'." }
    else {
        Assert-True (-not $caught) "Unexpected failure: $caught"
        Assert-True (Test-Path -LiteralPath (Join-Path $toolRoot '.install-complete') -PathType Leaf) 'Completion marker missing.'
        $settings = Get-Content -Raw -LiteralPath (Join-Path $caseRoot '.local/steamcmd.json') | ConvertFrom-Json
        Assert-True ($settings.executable -eq (Join-Path $toolRoot 'steamcmd.exe')) 'Settings must select the promoted client.'
    }
    $script:cases++
}
function Assert-NoStaging {
    Assert-True (@(Get-ChildItem -LiteralPath (Split-Path -Parent $toolRoot) -Directory -Filter 'steamcmd.staging-*').Count -eq 0) 'Staging was not cleaned.'
}
function Assert-TreeExited {
    $pidFile = Join-Path $caseRoot 'pids.txt'
    Assert-True (Test-Path -LiteralPath $pidFile) 'Hanging stand-in never started.'
    $ids = @(Get-Content -LiteralPath $pidFile)
    Assert-True ($ids.Count -eq 2) 'Stand-in must create a child to prove tree termination.'
    foreach ($processId in $ids) {
        $process = Get-Process -Id ([int]$processId) -ErrorAction SilentlyContinue
        if ($process) {
            $ownedProcesses.Add($process)
            Assert-True $process.HasExited "Stand-in process $processId survived the deadline."
        }
    }
}
try {
    New-Item -ItemType Directory -Path $fixture | Out-Null
    $source = Join-Path $fixture 'Client.cs'
    $exe = Join-Path $fixture 'steamcmd.exe'
    # Framework csc emits a standalone Windows executable without NuGet/network.
    Set-Content -LiteralPath $source -Value @'
using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
class Client {
    static int Main(string[] args) {
        string root = Environment.GetEnvironmentVariable("WIKI_STEAMCMD_FIXTURE");
        string mode = File.ReadAllText(Path.Combine(root, "mode.txt")).Trim();
        if (args.Length > 0 && args[0] == "child") { Thread.Sleep(Timeout.Infinite); return 0; }
        string calls = Path.Combine(root, "calls.txt");
        File.AppendAllText(calls, "call\n");
        int count = File.ReadAllLines(calls).Length;
        if (mode == "hang" || (mode == "second-hang" && count == 2)) {
            Process child = Process.Start(new ProcessStartInfo {
                FileName = Process.GetCurrentProcess().MainModule.FileName,
                Arguments = "child", UseShellExecute = false, CreateNoWindow = true
            });
            File.WriteAllLines(Path.Combine(root, "pids.txt"), new string[] {
                Process.GetCurrentProcess().Id.ToString(), child.Id.ToString()
            });
            Thread.Sleep(Timeout.Infinite);
        }
        if (mode == "fail") return 7;
        if ((mode == "self-update" || mode == "second-hang") && count == 1) return 1;
        return 0;
    }
}
'@
    $compiler = Join-Path $env:WINDIR 'Microsoft.NET/Framework64/v4.0.30319/csc.exe'
    & $compiler /nologo /target:exe "/out:$exe" $source
    Assert-True ($LASTEXITCODE -eq 0) 'Local stand-in compilation failed.'
    $archive = Join-Path $fixture 'bootstrap.zip'
    Compress-Archive -LiteralPath $exe -DestinationPath $archive

    New-Case
    Run-Installer
    Assert-NoStaging
    $marker = Get-Content -Raw -LiteralPath (Join-Path $toolRoot '.install-complete')
    Run-Installer # repeat must reuse the marked installation, not download again
    Assert-True (@(Get-Content -LiteralPath (Join-Path $caseRoot 'downloads.txt')).Count -eq 1) 'Repeat downloaded again.'
    Assert-True ((Get-Content -Raw -LiteralPath (Join-Path $toolRoot '.install-complete')) -eq $marker) 'Repeat changed the marker.'

    New-Case 'self-update'
    Run-Installer
    Assert-True (@(Get-Content -LiteralPath (Join-Path $caseRoot 'calls.txt')).Count -eq 2) 'Exit 1 must trigger confirmation.'

    foreach ($withClient in @($false, $true)) {
        New-Case
        New-Item -ItemType Directory -Path (Join-Path $toolRoot 'package'), (Join-Path $toolRoot 'logs') | Out-Null
        Set-Content -LiteralPath (Join-Path $toolRoot 'steamcmd.zip') -Value 'interrupted'
        Set-Content -LiteralPath (Join-Path $toolRoot 'package/steam_cmd_win32.manifest') -Value 'partial'
        Set-Content -LiteralPath (Join-Path $toolRoot 'logs/bootstrap_log.txt') -Value 'partial'
        if ($withClient) { Set-Content -LiteralPath (Join-Path $toolRoot 'steamcmd.exe') -Value 'partial client' }
        Run-Installer
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $toolRoot 'package/steam_cmd_win32.manifest'))) 'Interrupted contents survived replacement.'
    }

    foreach ($unknown in @('notes.txt', 'logs/notes.txt')) {
        New-Case
        New-Item -ItemType Directory -Path (Join-Path $toolRoot 'logs') | Out-Null
        $unknownFile = Join-Path $toolRoot $unknown
        Set-Content -LiteralPath $unknownFile -Value 'preserve me'
        Run-Installer 'Existing tool directory has no client'
        Assert-True ((Get-Content -LiteralPath $unknownFile) -eq 'preserve me') 'Unknown data was removed.'
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $caseRoot 'downloads.txt'))) 'Refused directory started a download.'
    }

    New-Case
    $leftover = Join-Path (Split-Path -Parent $toolRoot) ('steamcmd.staging-' + [guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $leftover | Out-Null
    Set-Content -LiteralPath (Join-Path $leftover 'steamcmd.zip') -Value 'partial'
    Run-Installer
    Assert-NoStaging

    foreach ($badSignature in @(
        @{ Status = 'NotSigned'; SignerCertificate = $null },
        @{ Status = 'Valid'; SignerCertificate = @{ Subject = 'CN=Other, O=Other, C=US' } }
    )) {
        New-Case
        $options.SignatureCheck = { param($Client) $badSignature }.GetNewClosure()
        Run-Installer 'SteamCMD must have a valid Valve signature'
        Assert-True (-not (Test-Path -LiteralPath $toolRoot)) 'Signature failure was promoted.'
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $caseRoot 'calls.txt'))) 'Unsigned client executed.'
        Assert-NoStaging
    }

    New-Case
    $signatureState = @{ Calls = 0 }
    $options.SignatureCheck = {
        param($Client)
        $signatureState.Calls++
        @{ Status = $(if ($signatureState.Calls -eq 1) { 'Valid' } else { 'NotSigned' }); SignerCertificate = @{ Subject = 'O=Valve Corp.' } }
    }.GetNewClosure()
    Run-Installer 'SteamCMD must have a valid Valve signature'
    Assert-True (-not (Test-Path -LiteralPath $toolRoot)) 'Invalid updated client was promoted.'

    foreach ($mode in @('hang', 'second-hang')) {
        New-Case $mode
        $watch = [System.Diagnostics.Stopwatch]::StartNew()
        Run-Installer '3 second deadline'
        Assert-True ($watch.Elapsed.TotalSeconds -lt 15) 'Bootstrap did not stop near its deadline.'
        Assert-TreeExited
        Assert-True (-not (Test-Path -LiteralPath $toolRoot)) 'Timed-out client was promoted.'
        Assert-NoStaging
    }

    New-Case 'hang'
    $options.Url = $exe
    $options.DownloadDeadlineSec = 3
    $options.Download = { param($Url, $Archive, $TimeoutSec) & $Url +quit }
    Run-Installer 'SteamCMD download exceeded its 3 second deadline'
    Assert-TreeExited
    Assert-NoStaging

    New-Case 'fail'
    Run-Installer 'SteamCMD setup failed with exit 7'
    Assert-True (@(Get-Content -LiteralPath (Join-Path $caseRoot 'calls.txt')).Count -eq 2) 'Failed confirmation was not checked.'
    Assert-True (-not (Test-Path -LiteralPath $toolRoot)) 'Failed confirmation was promoted.'

    New-Case
    $options.Download = { param($Url, $Archive, $TimeoutSec) Set-Content -LiteralPath $Archive -Value 'not a zip' }
    Run-Installer 'SteamCMD archive expansion failed'
    Assert-True (-not (Test-Path -LiteralPath $toolRoot)) 'Invalid archive was promoted.'
    Assert-NoStaging

} finally {
    # Only terminate exact fixture executables if an assertion failed mid-test.
    foreach ($pidFile in Get-ChildItem -LiteralPath $fixture -Filter pids.txt -Recurse -ErrorAction SilentlyContinue) {
        foreach ($processId in Get-Content -LiteralPath $pidFile.FullName) {
            $process = Get-Process -Id ([int]$processId) -ErrorAction SilentlyContinue
            if ($process -and $process.Path -and $process.Path.StartsWith($fixture + [System.IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
                $process.Kill($true)
                $process.WaitForExit()
                $process.Dispose()
            }
        }
    }
    foreach ($process in $ownedProcesses) { $process.Dispose() }
    $env:WIKI_STEAMCMD_FIXTURE = $previousFixture
    $resolved = [System.IO.Path]::GetFullPath($fixture)
    $allowed = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\', '/') + [System.IO.Path]::DirectorySeparatorChar
    if (-not $resolved.StartsWith($allowed, [StringComparison]::OrdinalIgnoreCase)) { throw 'Fixture cleanup escaped temp root.' }
    if (Test-Path -LiteralPath $resolved) { Remove-Item -LiteralPath $resolved -Recurse }
}
Assert-True (-not (Test-Path -LiteralPath $fixture)) 'Test fixture survived cleanup.'
Write-Host "$cases cases passed"
