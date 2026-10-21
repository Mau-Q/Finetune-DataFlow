[CmdletBinding()]
param([string]$Python = "python")
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "windows-common.ps1")

# Real native processes, including argument boundaries and nonzero exit status.
Invoke-CheckedNative $Python @("-c", "import sys; assert sys.argv[1] == 'path with spaces'", "path with spaces")
$failed = $false
try { Invoke-CheckedNative $Python @("-c", "raise SystemExit(23)") }
catch {
    if ($_.Exception.Message -notmatch 'exit code 23') { throw }
    $failed = $true
}
if (-not $failed) { throw "Nonzero native exit code was ignored" }

# Fail setup at its first external command; dependencies must not be installed.
function global:git { $global:LASTEXITCODE = 24 }
function global:uv { throw "uv must not run after git fails" }
function global:node { throw "node must not run" }
function global:npm { throw "npm must not run" }
try {
    $failed = $false
    try { & (Join-Path $PSScriptRoot "setup-windows.ps1") -SkipFrontend }
    catch {
        if ($_.Exception.Message -notmatch 'exit code 24') { throw }
        $failed = $true
    }
    if (-not $failed) { throw "Setup ignored failed submodule initialization" }
}
finally {
    foreach ($name in @("git", "uv", "node", "npm")) {
        Remove-Item "function:global:$name"
    }
}
Write-Host "Windows script regression tests passed."

# Exercise daemon handling in an isolated checkout whose path contains spaces.
$Fixture = Join-Path ([IO.Path]::GetTempPath()) ("dataflow test " + [guid]::NewGuid().ToString("N"))
$FixtureScripts = Join-Path $Fixture "scripts"
$FixtureBackend = Join-Path $Fixture "repos/dataflow-webui"
$FixtureVenv = Join-Path $Fixture ".venv/Scripts"
New-Item -ItemType Directory -Force $FixtureScripts, $FixtureBackend, $FixtureVenv | Out-Null
Copy-Item (Join-Path $PSScriptRoot "webui-windows.ps1"), (Join-Path $PSScriptRoot "windows-common.ps1") $FixtureScripts
$FixtureStart = Join-Path $FixtureScripts "webui-windows.ps1"
$FixturePid = Join-Path $FixtureBackend ".backend.pid"
$global:DataflowTestArguments = $null
function global:Get-Process { [pscustomobject]@{ Id = 42 } }
function global:Get-CimInstance { [pscustomobject]@{ ExecutablePath = "unrelated.exe"; CommandLine = "unrelated" } }
function global:Stop-Process { throw "An unrelated process must never be stopped" }
try {
    '42' | Set-Content $FixturePid
    $failed = $false
    try { & $FixtureStart -Action Stop }
    catch {
        if ($_.Exception.Message -notmatch 'does not identify this backend') { throw }
        $failed = $true
    }
    if (-not $failed) { throw "Stop accepted an unrelated process" }
    Remove-Item $FixturePid -Force
    New-Item -ItemType File (Join-Path $FixtureVenv "python.exe"), (Join-Path $FixtureVenv "Activate.ps1") | Out-Null
    function global:Get-Process { return $null }
    function global:Start-Process {
        param($FilePath, $ArgumentList, $WorkingDirectory, $RedirectStandardOutput,
              $RedirectStandardError, $WindowStyle, [switch]$PassThru)
        $global:DataflowTestArguments = $ArgumentList
        return [pscustomobject]@{ Id = 42 }
    }
    function global:Start-Sleep { }
    function global:Invoke-WebRequest { throw "fixture backend failed" }
    $failed = $false
    try { & $FixtureStart -Action Daemon }
    catch {
        if ($_.Exception.Message -notmatch 'Backend did not become ready') { throw }
        $failed = $true
    }
    if (-not $failed) { throw "Daemon readiness failure was ignored" }
    $ExpectedArgument = '"' + (Join-Path $FixtureScripts "windows_server.py") + '"'
    if ($global:DataflowTestArguments -cne $ExpectedArgument) { throw "Daemon server path was not quoted" }
}
finally {
    foreach ($name in @("Get-Process", "Get-CimInstance", "Stop-Process", "Start-Process", "Start-Sleep", "Invoke-WebRequest")) {
        Remove-Item "function:global:$name" -ErrorAction SilentlyContinue
    }
    Remove-Variable DataflowTestArguments -Scope Global -ErrorAction SilentlyContinue
    Remove-Item $Fixture -Recurse -Force
}
Write-Host "Windows daemon regression tests passed."
