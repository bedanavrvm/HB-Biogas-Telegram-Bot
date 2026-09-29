param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$TestLabels
)

$ErrorActionPreference = 'Stop'

$previousTestDatabaseUrl = $env:TEST_DATABASE_URL
if (-not $env:TEST_DATABASE_URL) {
    $securePassword = Read-Host 'Password for local PostgreSQL role jbl_test_runner' -AsSecureString
    $passwordPointer = [IntPtr]::Zero
    try {
        $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
        $plainPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
        $encodedPassword = [uri]::EscapeDataString($plainPassword)
        $env:TEST_DATABASE_URL = "postgresql://jbl_test_runner:$encodedPassword@127.0.0.1:5432/jbl_test"
    }
    finally {
        if ($passwordPointer -ne [IntPtr]::Zero) {
            [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
        }
        Remove-Variable securePassword,passwordPointer,plainPassword,encodedPassword -ErrorAction SilentlyContinue
    }
}

$python = Join-Path $PSScriptRoot '..\.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python virtual environment not found at $python"
}

$previousSettings = $env:DJANGO_SETTINGS_MODULE
$previousSecretKey = $env:DJANGO_SECRET_KEY
$env:DJANGO_SETTINGS_MODULE = 'config.settings_test_postgres'
$env:DJANGO_SECRET_KEY = 'local-postgres-test-only-' + [guid]::NewGuid().ToString('N')
$resultsDirectory = Join-Path $PSScriptRoot '..\test-results'
New-Item -ItemType Directory -Path $resultsDirectory -Force | Out-Null
$runTimestamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outputLog = Join-Path $resultsDirectory "postgres-tests-$runTimestamp.txt"
Start-Transcript -Path $outputLog -Force | Out-Null
Write-Host "Saving PostgreSQL test output to: $outputLog"
try {
    & $python (Join-Path $PSScriptRoot 'ensure_postgres_test_database.py')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    & $python (Join-Path $PSScriptRoot '..\manage.py') shell -c "from django.db import connection; connection.ensure_connection(); assert connection.vendor == 'postgresql'; cursor = connection.cursor(); cursor.execute('SHOW server_version'); print('PostgreSQL parity database:', connection.vendor, cursor.fetchone()[0]); cursor.close()"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

    $arguments = @((Join-Path $PSScriptRoot '..\manage.py'), 'test')
    if ($TestLabels.Count -gt 0) { $arguments += $TestLabels }
    $arguments += @('--noinput', '--verbosity', '1')
    & $python @arguments
    exit $LASTEXITCODE
}
finally {
    Stop-Transcript | Out-Null
    if ($null -eq $previousSettings) {
        Remove-Item Env:DJANGO_SETTINGS_MODULE -ErrorAction SilentlyContinue
    }
    else {
        $env:DJANGO_SETTINGS_MODULE = $previousSettings
    }
    if ($null -eq $previousSecretKey) {
        Remove-Item Env:DJANGO_SECRET_KEY -ErrorAction SilentlyContinue
    }
    else {
        $env:DJANGO_SECRET_KEY = $previousSecretKey
    }
    if ($null -eq $previousTestDatabaseUrl) {
        Remove-Item Env:TEST_DATABASE_URL -ErrorAction SilentlyContinue
    }
    else {
        $env:TEST_DATABASE_URL = $previousTestDatabaseUrl
    }
}
