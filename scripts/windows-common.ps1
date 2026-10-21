# Explicit checks also work in Windows PowerShell 5.1, where native nonzero
# exit codes do not trigger ErrorActionPreference = Stop.
function Invoke-CheckedNative {
    param(
        [Parameter(Mandatory = $true, Position = 0)][string]$Command,
        [Parameter(Position = 1)][string[]]$Arguments = @()
    )
    & $Command @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed with exit code ${LASTEXITCODE}: $Command"
    }
}
