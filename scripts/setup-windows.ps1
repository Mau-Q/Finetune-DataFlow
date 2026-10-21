[CmdletBinding()]
param(
    [switch]$SkipFrontend
)

$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root

function Require-Command([string]$Name) {
    if (-not (Get-Command $Name -ErrorAction SilentlyContinue)) {
        throw "Missing prerequisite: $Name"
    }
}

foreach ($tool in @("git", "uv", "node", "npm")) {
    Require-Command $tool
}

Write-Host "Initializing required submodules..."
& git submodule update --init -- repos/dataflow repos/dataflow-webui

$Python = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    Write-Host "Creating .venv with Python 3.12..."
    & uv venv --python 3.12 --seed (Join-Path $Root ".venv")
}

& $Python (Join-Path $Root "scripts\check-workspace.py")

$TempRoot = Join-Path ([IO.Path]::GetTempPath()) ("finetune-dataflow-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $TempRoot | Out-Null

try {
    $CoreRequirements = Join-Path $TempRoot "dataflow-windows.txt"
    $WebuiRequirements = Join-Path $TempRoot "webui-windows.txt"

    # langkit pulls whylogs-sketching, whose Windows/Python 3.12 installation
    # requires a native C++ build. Langkit is an optional evaluator and is
    # disabled by scripts/windows_server.py when unavailable.
    Get-Content (Join-Path $Root "repos\dataflow\requirements.txt") |
        Where-Object { $_ -notmatch '^\s*langkit\s*$' } |
        Set-Content -Encoding utf8 $CoreRequirements

    # Install the local editable DataFlow package below. Do not let the
    # published open-dataflow requirement pull a second copy and its full
    # dependency graph back into the Windows environment.
    Get-Content (Join-Path $Root "repos\dataflow-webui\backend\requirements.txt") |
        Where-Object { $_ -notmatch '^\s*open-dataflow(?:==.*)?\s*$' } |
        Set-Content -Encoding utf8 $WebuiRequirements

    Write-Host "Installing the local DataFlow package without dependency re-resolution..."
    & uv pip install --python $Python --no-deps -e (Join-Path $Root "repos\dataflow")
    & uv pip install --python $Python -r $CoreRequirements -r $WebuiRequirements -r (Join-Path $Root "locks\dataflow-test.txt")
    & uv pip install --python $Python --no-deps -e (Join-Path $Root "extensions\paper-dataflow")

    if (-not $SkipFrontend) {
        Push-Location (Join-Path $Root "repos\dataflow-webui\frontend")
        try {
            & npm ci --no-audit --no-fund
            & npm run build
        }
        finally {
            Pop-Location
        }
    }

    Write-Host "Windows environment ready. Start with: .\scripts\webui-windows.ps1 -Action Foreground"
}
finally {
    Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue
}
