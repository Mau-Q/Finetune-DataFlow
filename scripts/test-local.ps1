[CmdletBinding()]
param([string]$Python = '')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'windows-common.ps1')
$Root = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
if (-not $Python) { $Python = Join-Path $Root '.venv/Scripts/python.exe' }
$Python = (Get-Command $Python -ErrorAction Stop).Source
$OldPythonPath = $env:PYTHONPATH
$OldUtf8 = $env:PYTHONUTF8
Push-Location $Root
try {
    # Match the production launcher, including inherited Python subprocesses.
    $env:PYTHONUTF8 = '1'
    $env:PYTHONPATH = @((Join-Path $Root 'repos/dataflow-webui/backend'), (Join-Path $Root 'repos/dataflow'), $OldPythonPath) -join [IO.Path]::PathSeparator
    Invoke-CheckedNative $Python @('-m', 'pytest', 'repos/dataflow/test/cpu_only', '-q', '-m', 'not gpu')
    Invoke-CheckedNative $Python @('-m', 'pytest', 'repos/dataflow-webui/backend/tests', '-q')
    Invoke-CheckedNative $Python @('-m', 'pytest', 'extensions/paper-dataflow/test', '-q')
}
finally {
    $env:PYTHONPATH = $OldPythonPath
    $env:PYTHONUTF8 = $OldUtf8
    Pop-Location
}
