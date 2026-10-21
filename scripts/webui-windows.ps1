[CmdletBinding()]
param(
    [ValidateSet("Foreground", "Daemon", "Status", "Stop")]
    [string]$Action = "Foreground"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "windows-common.ps1")
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Activate = Join-Path $Root ".venv\Scripts\Activate.ps1"
$Server = Join-Path $Root "scripts\windows_server.py"
$Backend = Join-Path $Root "repos\dataflow-webui\backend"
$PidFile = Join-Path $Root "repos\dataflow-webui\.backend.pid"
$LogFile = Join-Path $Root "repos\dataflow-webui\.backend.log"
$ErrorLogFile = Join-Path $Root "repos\dataflow-webui\.backend.error.log"

$BindHost = if ($env:DATAFLOW_HOST) { $env:DATAFLOW_HOST } else { "127.0.0.1" }
$Port = if ($env:DATAFLOW_PORT) { [int]$env:DATAFLOW_PORT } else { 8000 }
$env:DATAFLOW_HOST = $BindHost
$env:DATAFLOW_PORT = "$Port"
$env:HF_HOME = Join-Path $Root "models\huggingface-cache"

function Get-BackendProcess {
    if (-not (Test-Path $PidFile)) { return $null }
    $processId = 0
    if (-not [int]::TryParse((Get-Content -Raw $PidFile).Trim(), [ref]$processId) -or $processId -le 0) {
        throw "Invalid backend PID file: $PidFile"
    }
    $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
    if ($null -eq $process) { return $null }
    # A stale PID may have been reused by another application. Refuse to stop it.
    $details = Get-CimInstance Win32_Process -Filter "ProcessId = $processId" -ErrorAction Stop
    if ($null -eq $details -or $details.ExecutablePath -ine $Python -or
        $details.CommandLine -notmatch [regex]::Escape($Server)) {
        throw "PID $processId does not identify this backend. Inspect and remove stale PID file: $PidFile"
    }
    return $process
}

if ($Action -in @("Foreground", "Daemon")) {
    if (-not (Test-Path $Python)) {
        throw "Python environment not found: $Python. Run .\scripts\setup-windows.ps1 first."
    }
    if (-not (Test-Path $Activate)) {
        throw "Virtual environment activation script not found: $Activate. Run .\scripts\setup-windows.ps1 first."
    }
}

switch ($Action) {
    "Status" {
        $process = Get-BackendProcess
        if ($null -eq $process) {
            Write-Host "Backend is not running."
            exit 1
        }
        try {
            Invoke-WebRequest -UseBasicParsing "http://$BindHost`:$Port/api/v1/datasets/" -TimeoutSec 3 | Out-Null
            Write-Host "Backend is running at http://$BindHost`:$Port (PID $($process.Id))."
        }
        catch {
            Write-Host "Process $($process.Id) exists, but the backend is not ready yet."
            exit 1
        }
        break
    }
    "Stop" {
        $process = Get-BackendProcess
        if ($null -eq $process) {
            Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
            Write-Host "Backend is not running."
            break
        }
        Stop-Process -Id $process.Id -Force
        Remove-Item -LiteralPath $PidFile -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped backend (PID $($process.Id))."
        break
    }
    "Daemon" {
        if ($null -ne (Get-BackendProcess)) {
            Write-Host "Backend is already running."
            break
        }
        $process = Start-Process -FilePath $Python `
            -ArgumentList @('"' + $Server + '"') `
            -WorkingDirectory $Backend `
            -RedirectStandardOutput $LogFile `
            -RedirectStandardError $ErrorLogFile `
            -WindowStyle Hidden `
            -PassThru
        $process.Id | Set-Content -Encoding ascii $PidFile
        Write-Host "Started backend (PID $($process.Id)). Logs: $LogFile"
        $ready = $false
        for ($attempt = 0; $attempt -lt 60; $attempt++) {
            Start-Sleep -Seconds 1
            try {
                Invoke-WebRequest -UseBasicParsing "http://$BindHost`:$Port/api/v1/datasets/" -TimeoutSec 2 | Out-Null
                $ready = $true
                break
            }
            catch {
                if ($null -eq (Get-BackendProcess)) { break }
            }
        }
        if ($ready) {
            Write-Host "Backend ready at http://$BindHost`:$Port."
        }
        else {
            throw "Backend did not become ready. Check $LogFile and $ErrorLogFile."
        }
        break
    }
    "Foreground" {
        Write-Host "Activating virtual environment: .venv"
        . $Activate
        $activePython = (Get-Command python -ErrorAction Stop).Source
        Write-Host "Virtual environment: $env:VIRTUAL_ENV"
        Write-Host "Python: $activePython"
        Write-Host "WebUI logs are shown below. Press Ctrl+C to stop."
        Push-Location $Backend
        try {
            Invoke-CheckedNative $Python @($Server)
        }
        finally {
            Pop-Location
        }
        break
    }
}
