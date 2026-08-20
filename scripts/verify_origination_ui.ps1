param(
    [int]$Port = 8765,
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = 'Stop'
$repository = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$auditRoot = Join-Path ([System.IO.Path]::GetTempPath()) 'hb-origination-playwright'
$legacyAuditRoot = Join-Path ([System.IO.Path]::GetTempPath()) 'hb-origination-visual-audit'
$auditDatabase = Join-Path ([System.IO.Path]::GetTempPath()) ('hb-origination-ui-' + [guid]::NewGuid().ToString('N') + '.sqlite3')
if (-not $OutputDirectory) { $OutputDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ('hb-origination-ui-' + [guid]::NewGuid().ToString('N')) }

if (Test-Path (Join-Path $legacyAuditRoot 'node_modules\playwright')) {
    $auditRoot = $legacyAuditRoot
} else {
    New-Item -ItemType Directory -Force -Path $auditRoot | Out-Null
}
if (-not (Test-Path (Join-Path $auditRoot 'node_modules\playwright'))) {
    npm.cmd install --prefix $auditRoot playwright@1.62.1 --no-save --no-audit --no-fund
}

$env:DEBUG = 'true'
$env:DJANGO_SECRET_KEY = 'synthetic-origination-ui-audit-key'
$env:DATABASE_URL = 'sqlite:///' + ($auditDatabase -replace '\\', '/')
$env:NODE_PATH = Join-Path $auditRoot 'node_modules'
$env:ORIGINATION_AUDIT_URL = "http://127.0.0.1:$Port/origination/"
$env:ORIGINATION_AUDIT_OUTPUT = $OutputDirectory
$stdout = Join-Path $auditRoot 'django-ui-audit.log'
$stderr = Join-Path $auditRoot 'django-ui-audit.err.log'
$server = $null

# Some Windows agent shells expose both `Path` and `PATH`. Start-Process builds
# a case-insensitive environment dictionary and otherwise fails before Django
# starts. Preserve both values under the canonical Windows key.
$processEnvironment = [System.Environment]::GetEnvironmentVariables()
$combinedPath = (@($processEnvironment['Path'], $processEnvironment['PATH']) | Where-Object { $_ }) -join ';'
[System.Environment]::SetEnvironmentVariable('PATH', $null, 'Process')
[System.Environment]::SetEnvironmentVariable('Path', $combinedPath, 'Process')

try {
    & "$repository\.venv\Scripts\python.exe" manage.py migrate --noinput | Out-Null
    $server = Start-Process -FilePath "$repository\.venv\Scripts\python.exe" -ArgumentList @('manage.py', 'runserver', "127.0.0.1:$Port", '--noreload') -WorkingDirectory $repository -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try {
            Invoke-WebRequest -UseBasicParsing $env:ORIGINATION_AUDIT_URL -TimeoutSec 2 | Out-Null
            $ready = $true
            break
        } catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $ready) { throw "Django did not become ready. See $stderr" }
    node (Join-Path $repository 'scripts\origination_ui_audit.js')
    if ($LASTEXITCODE -ne 0) { throw "Origination browser audit failed with exit code $LASTEXITCODE" }
} finally {
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
    if (Test-Path -LiteralPath $auditDatabase) { Remove-Item -LiteralPath $auditDatabase -Force }
}
