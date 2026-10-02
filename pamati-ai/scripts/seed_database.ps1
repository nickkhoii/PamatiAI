param([switch]$DevelopmentAccounts)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
Push-Location "$projectRoot/backend"
try {
    $seedArguments = @('-m', 'app.database_commands', 'seed')
    if ($DevelopmentAccounts) { $seedArguments += '--development-accounts' }
    & "$projectRoot/.venv/Scripts/python.exe" @seedArguments
    if ($LASTEXITCODE -ne 0) { throw 'Database seed failed' }
} finally { Pop-Location }
