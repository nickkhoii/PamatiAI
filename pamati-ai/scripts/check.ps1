$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location "$projectRoot/backend"
try {
    & "$projectRoot/.venv/Scripts/python.exe" -m pytest
    if ($LASTEXITCODE -ne 0) { throw 'Backend tests failed' }
    & "$projectRoot/.venv/Scripts/python.exe" -m ruff check app ../tests/backend
    if ($LASTEXITCODE -ne 0) { throw 'Backend lint failed' }
    & "$projectRoot/.venv/Scripts/python.exe" -m alembic upgrade head --sql
    if ($LASTEXITCODE -ne 0) { throw 'Migration SQL generation failed' }
} finally { Pop-Location }
Push-Location "$projectRoot/frontend"
try {
    npm.cmd test
    if ($LASTEXITCODE -ne 0) { throw 'Frontend tests failed' }
    npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed' }
    npm.cmd run typecheck
    if ($LASTEXITCODE -ne 0) { throw 'Frontend type check failed' }
} finally { Pop-Location }
