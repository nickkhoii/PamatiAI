$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location "$projectRoot/backend"
try {
    & "$projectRoot/.venv/Scripts/python.exe" -m app.database_commands init
    if ($LASTEXITCODE -ne 0) { throw 'Database initialization failed' }
} finally { Pop-Location }
