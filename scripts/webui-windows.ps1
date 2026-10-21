[CmdletBinding()]
param(
    [ValidateSet("Foreground", "Daemon", "Status", "Stop")]
    [string]$Action = "Foreground"
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$Python = Join-Path $Root ".venv\Scripts\python.exe"
$Activate = Join-Path $Root ".venv\Scripts\Activate.ps1"
$Server = Join-Path $Root "scripts\windows_server.py"
$Backend = Join-Path $Root "repos\dataflow-webui\backend"
$PidFile = Join-Path $Root "repos\dataflow-webui\.backend.pid"
$LogFile = Join-Path $Root "repos\dataflow-webui\.backend.log"
$ErrorLogFile = Join-Path $Root "repos\dataflow-webui\.backend.error.log"

if (-not (Test-Path $Python)) {
    throw "Python environment not found: $Python. Run .\scripts\setup-windows.ps1 first."
}

if (-not (Test-Path $Activate)) {
    throw "Virtual environment activation script not found: $Activate. Run .\scripts\setup-windows.ps1 first."
}

$BindHost = if ($env:DATAFLOW_HOST) { $env:DATAFLOW_HOST } else { "127.0.0.1" }
$Port = if ($env:DATAFLOW_PORT) { [int]$env:DATAFLOW_PORT } else { 8000 }
$env:DATAFLOW_HOST = $BindHost
$env:DATAFLOW_PORT = "$Port"
$env:HF_HOME = Join-Path $Root "models\huggingface-cache"

function Get-BackendProcess {
    if (-not (Test-Path $PidFile)) { return $null }
    $processId = [int](Get-Content -Raw $PidFile)
    return Get-Process -Id $processId -ErrorAction SilentlyContinue
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
            -ArgumentList @($Server) `
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
            Write-Warning "Backend did not become ready within 60 seconds. Check $LogFile and $ErrorLogFile."
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
            & python $Server
        }
        finally {
            Pop-Location
        }
        break
    }
}
