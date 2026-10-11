param([string]$Output = 'dist')
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (!(Test-Path -LiteralPath '.venv\Scripts\python.exe')) { throw 'Run Setup.ps1 first' }
    & .\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
    if ($LASTEXITCODE -ne 0) { throw 'Build dependency installation failed' }
    & .\.venv\Scripts\python.exe -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'Tests failed; bundle was not built' }
    & .\.venv\Scripts\python.exe build_windows.py --output $Output
    if ($LASTEXITCODE -ne 0) { throw 'Windows build failed' }
    Write-Output 'Ready: CarromAIShowdown folder. Keep the EXE and _internal together.'
} finally { Pop-Location }
