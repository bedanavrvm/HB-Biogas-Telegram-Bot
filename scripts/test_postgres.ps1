param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$TestLabels
)

$ErrorActionPreference = 'Stop'

if (-not $env:TEST_DATABASE_URL) {
    throw 'Set TEST_DATABASE_URL to a local PostgreSQL database owned by a role with CREATEDB.'
}

$python = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python virtual environment not found at $python"
}

$previousSettings = $env:DJANGO_SETTINGS_MODULE
$env:DJANGO_SETTINGS_MODULE = 'config.settings_test_postgres'
try {
    & $python (Join-Path $PSScriptRoot '..\manage.py') shell -c "from django.db import connection; connection.ensure_connection(); assert connection.vendor == 'postgresql'; cursor = connection.cursor(); cursor.execute('SHOW server_version'); print('PostgreSQL parity database:', connection.vendor, cursor.fetchone()[0]); cursor.close()"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    $arguments = @((Join-Path $PSScriptRoot '..\manage.py'), 'test')
    if ($TestLabels.Count -gt 0) { $arguments += $TestLabels }
    $arguments += @('--noinput', '--verbosity', '1')
    & $python @arguments
    exit $LASTEXITCODE
}
finally {
    if ($null -eq $previousSettings) {
        Remove-Item Env:DJANGO_SETTINGS_MODULE -ErrorAction SilentlyContinue
    }
    else {
        $env:DJANGO_SETTINGS_MODULE = $previousSettings
    }
}
