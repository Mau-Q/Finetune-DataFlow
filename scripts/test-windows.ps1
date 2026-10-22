[CmdletBinding()]
param([string]$Python = "python")
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "windows-common.ps1")

# Parse the GUI adapter without opening a dialog, including on PowerShell 5.1.
$PickerScript = Join-Path $PSScriptRoot "../repos/dataflow-webui/backend/app/services/desktop_picker.ps1"
$ParseErrors = $null
$ParseTokens = $null
[System.Management.Automation.Language.Parser]::ParseFile($PickerScript, [ref]$ParseTokens, [ref]$ParseErrors) | Out-Null
if ($ParseErrors.Count -gt 0) { throw ($ParseErrors | Out-String) }

# Real native processes, including argument boundaries and nonzero exit status.
Invoke-CheckedNative $Python @("-c", "import sys; assert sys.argv[1] == 'path with spaces'", "path with spaces")
$failed = $false
try { Invoke-CheckedNative $Python @("-c", "raise SystemExit(23)") }
catch {
    if ($_.Exception.Message -notmatch 'exit code 23') { throw }
    $failed = $true
}
if (-not $failed) { throw "Nonzero native exit code was ignored" }

# Fail setup in an isolated missing-source checkout; never modify this checkout.
$SetupFixture = Join-Path ([IO.Path]::GetTempPath()) ("dataflow setup " + [guid]::NewGuid().ToString("N"))
$SetupScripts = Join-Path $SetupFixture "scripts"
New-Item -ItemType Directory -Force $SetupScripts | Out-Null
Copy-Item (Join-Path $PSScriptRoot "setup-windows.ps1"), (Join-Path $PSScriptRoot "windows-common.ps1") $SetupScripts
function global:git { $global:LASTEXITCODE = 24 }
function global:uv { throw "uv must not run after source validation fails" }
function global:node { throw "node must not run" }
function global:npm { throw "npm must not run" }
$OriginalDirectory = Get-Location
try {
    $failed = $false
    try { & (Join-Path $SetupScripts "setup-windows.ps1") -SkipFrontend }
    catch {
        if ($_.Exception.Message -notmatch 'Missing repository source') { throw }
        $failed = $true
    }
    if (-not $failed) { throw "Setup ignored missing repository source" }
}
finally {
    Set-Location $OriginalDirectory
    foreach ($name in @("git", "uv", "node", "npm")) {
        Remove-Item "function:global:$name"
    }
    Remove-Item $SetupFixture -Recurse -Force
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
    function global:Get-CimInstance {
        [pscustomobject]@{ ExecutablePath = (Join-Path $FixtureVenv "python.exe"); CommandLine = (Join-Path $FixtureScripts "windows_server.py") }
    }
    function global:taskkill.exe {
        $global:DataflowTestArguments = @($args)
        $global:LASTEXITCODE = 0
    }
    & $FixtureStart -Action Stop
    if (($global:DataflowTestArguments -join ' ') -cne '/PID 42 /T /F') { throw "Stop did not target the verified process tree" }
    Remove-Item $FixturePid -Force -ErrorAction SilentlyContinue
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
    foreach ($name in @("Get-Process", "Get-CimInstance", "Stop-Process", "Start-Process", "Start-Sleep", "Invoke-WebRequest", "taskkill.exe")) {
        Remove-Item "function:global:$name" -ErrorAction SilentlyContinue
    }
    Remove-Variable DataflowTestArguments -Scope Global -ErrorAction SilentlyContinue
    Remove-Item $Fixture -Recurse -Force
}
Write-Host "Windows daemon regression tests passed."
# Expected native failures above leave LASTEXITCODE nonzero. GitHub's Windows
# PowerShell wrapper propagates it unless the test runner reports success.
exit 0
