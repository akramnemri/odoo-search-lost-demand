# First command after cloning (Windows): checks uv, installs the project environment, runs the doctor.
# Usage (from the repository root): powershell -ExecutionPolicy Bypass -File scripts\bootstrap.ps1
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath (Split-Path -Parent $PSScriptRoot)

if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    Write-Host 'uv is not installed. Official install command (current user only, no administrator rights):'
    Write-Host '  winget install --id astral-sh.uv -e --source winget'
    $answer = Read-Host 'Run it now? [y/N]'
    if ($answer -notmatch '^(y|yes)$') {
        Write-Host 'Install uv, open a new terminal, then run this script again.'
        exit 1
    }
    winget install --id astral-sh.uv -e --source winget
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    # winget updates the user PATH for new terminals only; reload it for this session.
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'User') + ';' + [Environment]::GetEnvironmentVariable('Path', 'Machine')
}

uv sync
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run shop doctor
exit $LASTEXITCODE
