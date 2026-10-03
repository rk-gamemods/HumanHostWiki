#Requires -Version 7
# Dot-sourced implementation. Only the fixed production entrypoint runs setup.
function Assert-SteamInstallPath([string]$WikiRoot, [string]$Path) {
    $root = [System.IO.Path]::GetFullPath($WikiRoot).TrimEnd('\', '/')
    $fullPath = [System.IO.Path]::GetFullPath($Path)
    if ($fullPath -ne $root -and -not $fullPath.StartsWith($root + [System.IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
        throw "SteamCMD path is outside wiki root: $Path"
    }
    # Check every existing ancestor, including the root's ancestors. With no
    # reparse points, the canonical full path is also the physical path.
    for ($current = $fullPath; $current; $current = Split-Path -Parent $current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                throw "SteamCMD path contains a junction or symlink: $current"
            }
        }
    }
}

function Assert-SteamInstallTree([string]$WikiRoot, [string]$Path) {
    Assert-SteamInstallPath $WikiRoot $Path
    foreach ($entry in Get-ChildItem -LiteralPath $Path -Recurse -Force) {
        if ($entry.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            throw "SteamCMD tree contains a junction or symlink: $($entry.FullName)"
        }
    }
}

function Write-SteamInstallOwner([string]$WikiRoot, [string]$Path) {
    Assert-SteamInstallPath $WikiRoot $Path
    $receipt = @{
        owner = 'HumanHostWiki SteamCMD installer'
        id = [guid]::NewGuid().ToString()
        created_utc = [datetime]::UtcNow.ToString('o')
    } | ConvertTo-Json
    # CreateNew cannot silently overwrite a pre-existing claim of ownership.
    $stream = [System.IO.File]::Open((Join-Path $Path '.hhwiki-steamcmd-owner.json'), 'CreateNew', 'Write', 'None')
    try {
        $bytes = [System.Text.UTF8Encoding]::new($false).GetBytes($receipt + "`n")
        $stream.Write($bytes, 0, $bytes.Length)
    } finally { $stream.Dispose() }
}

function Assert-SteamInstallOwner([string]$WikiRoot, [string]$Path) {
    Assert-SteamInstallTree $WikiRoot $Path
    $receiptPath = Join-Path $Path '.hhwiki-steamcmd-owner.json'
    try {
        $receipt = Get-Content -Raw -LiteralPath $receiptPath | ConvertFrom-Json
        $ownerId = [guid]::Empty
        $created = [datetime]::MinValue
        if ($receipt.owner -ne 'HumanHostWiki SteamCMD installer' -or
            -not [guid]::TryParse($receipt.id, [ref]$ownerId) -or $ownerId -eq [guid]::Empty -or
            -not [datetime]::TryParse($receipt.created_utc, [ref]$created)) { throw 'Invalid receipt' }
    } catch { throw "Unowned SteamCMD directory; ownership receipt missing or invalid. Inspect before retrying: $Path" }
}

function Stop-SteamInstallProcess([System.Diagnostics.Process]$Process) {
    $watch = [System.Diagnostics.Stopwatch]::StartNew()
    $killer = $null
    try {
        # taskkill catches Windows children that .NET's tree kill can miss.
        $killer = Start-Process -FilePath (Join-Path $env:WINDIR 'System32/taskkill.exe') `
            -ArgumentList @('/T', '/F', '/PID', $Process.Id) -PassThru -NoNewWindow
        if (-not $killer.WaitForExit(5000)) {
            $killer.Kill()
            $null = $killer.WaitForExit(1000)
        }
    } catch { Write-Warning "SteamCMD taskkill failed; attempting .NET tree kill: $($_.Exception.Message)" }
    finally { if ($killer) { $killer.Dispose() } }
    if (-not $Process.HasExited) {
        try { $Process.Kill($true) }
        catch { Write-Warning "SteamCMD fallback tree kill failed: $($_.Exception.Message)" }
    }
    $remaining = [Math]::Max(0, 30000 - [int]$watch.ElapsedMilliseconds)
    if (-not $Process.WaitForExit($remaining)) {
        throw "SteamCMD process $($Process.Id) is still alive after the 30 second cleanup deadline."
    }
}

function Invoke-SteamInstallProcess([string]$FilePath, [string[]]$Arguments, [string]$WorkingDirectory, [int]$DeadlineSec, [string]$Name) {
    $process = Start-Process -FilePath $FilePath -ArgumentList $Arguments -WorkingDirectory $WorkingDirectory -PassThru -NoNewWindow
    $cleanupAttempted = $false
    try {
        if (-not $process.WaitForExit($DeadlineSec * 1000)) {
            $cleanupAttempted = $true
            try { Stop-SteamInstallProcess $process }
            catch { throw "$Name exceeded its $DeadlineSec second deadline. $($_.Exception.Message)" }
            throw "$Name exceeded its $DeadlineSec second deadline."
        }
        return $process.ExitCode
    } finally {
        try {
            if (-not $cleanupAttempted -and -not $process.HasExited) { Stop-SteamInstallProcess $process }
        } finally { $process.Dispose() }
    }
}

function Assert-ValveClient([string]$Client, [scriptblock]$SignatureCheck) {
    $signature = & $SignatureCheck $Client
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch '(^|, )O=Valve( Corp\.)?(,|$)') {
        throw "SteamCMD must have a valid Valve signature: $Client"
    }
}

function Install-SteamMetadataClient {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)][string]$WikiRoot,
        [Parameter(Mandatory)][string]$Url,
        [Parameter(Mandatory)][ValidateRange(1, 2147483)][int]$DownloadTimeoutSec,
        [Parameter(Mandatory)][ValidateRange(1, 2147483)][int]$DownloadDeadlineSec,
        [Parameter(Mandatory)][ValidateRange(1, 2147483)][int]$BootstrapDeadlineSec,
        [Parameter(Mandatory)][scriptblock]$Download,
        [Parameter(Mandatory)][scriptblock]$SignatureCheck
    )
    $ErrorActionPreference = 'Stop'
    $WikiRoot = [System.IO.Path]::GetFullPath($WikiRoot)
    $toolsRoot = Join-Path $WikiRoot '.local/tools'
    $toolRoot = Join-Path $toolsRoot 'steamcmd'
    $lockPath = Join-Path $toolsRoot 'steamcmd.lock'
    Assert-SteamInstallPath $WikiRoot $toolRoot
    Assert-SteamInstallPath $WikiRoot $lockPath
    if (-not (Test-Path -LiteralPath $toolsRoot)) { New-Item -ItemType Directory -Path $toolsRoot | Out-Null }
    Assert-SteamInstallPath $WikiRoot $lockPath
    try { $lock = [System.IO.File]::Open($lockPath, 'OpenOrCreate', 'ReadWrite', 'None') }
    catch [System.IO.IOException] { throw "Another SteamCMD installer may be running; cannot acquire exclusive lock: $lockPath" }
    $staging = $null
    try {
        foreach ($leftover in Get-ChildItem -LiteralPath $toolsRoot -Directory -Filter 'steamcmd.staging-*' -Force) {
            Assert-SteamInstallOwner $WikiRoot $leftover.FullName
            Remove-Item -LiteralPath $leftover.FullName -Recurse
        }
        if (Test-Path -LiteralPath $toolRoot) {
            Assert-SteamInstallOwner $WikiRoot $toolRoot
            if (-not (Test-Path -LiteralPath (Join-Path $toolRoot '.install-complete') -PathType Leaf)) {
                Remove-Item -LiteralPath $toolRoot -Recurse
            } elseif (-not (Test-Path -LiteralPath (Join-Path $toolRoot 'steamcmd.exe') -PathType Leaf)) {
                throw "Existing tool directory has no client. Inspect it before retrying: $toolRoot"
            }
        }
        $installRoot = $toolRoot
        if (-not (Test-Path -LiteralPath $toolRoot)) {
            $staging = Join-Path $toolsRoot ('steamcmd.staging-' + [guid]::NewGuid().ToString('N'))
            Assert-SteamInstallPath $WikiRoot $staging
            New-Item -ItemType Directory -Path $staging | Out-Null
            Write-SteamInstallOwner $WikiRoot $staging
            $archive = Join-Path $staging 'steamcmd.zip'
            $downloadArgs = (@($Url, $archive, $DownloadTimeoutSec) | ForEach-Object { "'" + "$_".Replace("'", "''") + "'" }) -join ' '
            $downloadCode = '$ErrorActionPreference = ''Stop''; $ProgressPreference = ''SilentlyContinue''; & {' + $Download.ToString() + '} ' + $downloadArgs
            $encoded = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes($downloadCode))
            $exitCode = Invoke-SteamInstallProcess (Join-Path $PSHOME 'pwsh.exe') @('-NoProfile', '-EncodedCommand', $encoded) $staging $DownloadDeadlineSec 'SteamCMD download'
            if ($exitCode -ne 0) { throw "SteamCMD download failed with exit $exitCode" }
            try { Expand-Archive -LiteralPath $archive -DestinationPath $staging -ErrorAction Stop }
            catch { throw "SteamCMD archive expansion failed: $($_.Exception.Message)" }
            $installRoot = $staging
        }
        Assert-SteamInstallOwner $WikiRoot $installRoot
        $client = Join-Path $installRoot 'steamcmd.exe'
        if (-not (Test-Path -LiteralPath $client -PathType Leaf)) { throw "SteamCMD archive has no client: $client" }
        Assert-ValveClient $client $SignatureCheck
        # The first bootstrap may self-update and exit 1; confirmation must pass.
        $exitCode = Invoke-SteamInstallProcess $client @('+quit') $installRoot $BootstrapDeadlineSec 'SteamCMD bootstrap'
        if ($exitCode -ne 0) {
            Assert-ValveClient $client $SignatureCheck
            $exitCode = Invoke-SteamInstallProcess $client @('+quit') $installRoot $BootstrapDeadlineSec 'SteamCMD bootstrap confirmation'
        }
        if ($exitCode -ne 0) { throw "SteamCMD setup failed with exit $exitCode" }
        Assert-ValveClient $client $SignatureCheck
        if ($staging) {
            Assert-SteamInstallOwner $WikiRoot $staging
            Assert-SteamInstallPath $WikiRoot $toolRoot
            [System.IO.Directory]::Move($staging, $toolRoot)
            # The ownership receipt moves with staging, before this mutation.
            Assert-SteamInstallOwner $WikiRoot $toolRoot
            [System.IO.File]::WriteAllText((Join-Path $toolRoot '.install-complete'), "SteamCMD installer complete`n")
        }
        $client = Join-Path $toolRoot 'steamcmd.exe'
        $settings = Join-Path $WikiRoot '.local/steamcmd.json'
        Assert-SteamInstallPath $WikiRoot $settings
        $payload = @{ executable = $client } | ConvertTo-Json
        if (Test-Path -LiteralPath $settings) {
            $existing = Get-Content -Raw -LiteralPath $settings | ConvertFrom-Json
            if ($existing.executable -ne $client) { throw "Preserving different configured metadata client: $settings" }
        } else {
            [System.IO.File]::WriteAllText($settings, $payload + "`n", [System.Text.UTF8Encoding]::new($false))
        }
        Write-Output "Steam metadata client ready: $client"
    } finally {
        try {
            if ($staging -and (Test-Path -LiteralPath $staging)) {
                Assert-SteamInstallOwner $WikiRoot $staging
                Remove-Item -LiteralPath $staging -Recurse
            }
        } catch {
            # Keep the original failure (especially a surviving process report)
            # when files cannot be removed. A later locked invocation can recover.
            Write-Warning "Preserving incomplete SteamCMD staging at ${staging}: $($_.Exception.Message)"
        } finally { $lock.Dispose() }
    }
}
