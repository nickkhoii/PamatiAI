$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location "$projectRoot/backend"
try {
    & "$projectRoot/.venv/Scripts/python.exe" -m pytest
    if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed' }
} finally { Pop-Location }
Push-Location "$projectRoot/frontend"
try {
    npm.cmd test
    if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
} finally { Pop-Location }
