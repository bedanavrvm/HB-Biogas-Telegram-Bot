param([string]$NodePath = '')

$ErrorActionPreference = 'Stop'
$reviewEnvironment = @{}
foreach ($reviewName in @('PATH', 'PARCEL_WORKERS', 'RUN_STAFF_BROWSER_E2E', 'RUN_COMPLAINTS_LOCAL_REVIEW', 'SECRET_KEY', 'DJANGO_SECRET_KEY', 'DEBUG', 'SENTRY_DSN', 'SENTRY_BROWSER_DSN')) {
    $reviewEnvironment[$reviewName] = [Environment]::GetEnvironmentVariable($reviewName, 'Process')
}
$reviewRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
Push-Location $reviewRoot
try {
    if (-not $NodePath) {
        $reviewCandidates = @(
            (Join-Path $reviewRoot 'test-results/node-v22.23.3/node.exe')
            (Get-Command node -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
        )
        $reviewCache = Join-Path $env:LOCALAPPDATA 'npm-cache/_npx'
        if (Test-Path -LiteralPath $reviewCache) {
            $reviewCandidates += Get-ChildItem -LiteralPath $reviewCache -Directory |
                ForEach-Object { Join-Path $_.FullName 'node_modules/node/bin/node.exe' }
        }
        foreach ($reviewCandidate in $reviewCandidates) {
            if ($reviewCandidate -and (Test-Path -LiteralPath $reviewCandidate)) {
                $reviewVersion = & $reviewCandidate --version
                if ($LASTEXITCODE -eq 0 -and $reviewVersion -match '^v22\.') { $NodePath = $reviewCandidate; break }
            }
        }
    }
    if (-not $NodePath -or -not (Test-Path -LiteralPath $NodePath)) { throw 'Node 22 is required. Pass its executable using -NodePath.' }
    if ((& $NodePath --version) -notmatch '^v22\.') { throw 'Use Node 22 for the pinned browser build.' }
    $reviewPython = Join-Path $reviewRoot '.venv/Scripts/python.exe'
    if (-not (Test-Path -LiteralPath $reviewPython)) { throw 'The repository .venv is required.' }
    $env:PATH = "$(Split-Path $NodePath);$env:PATH"
    $env:PARCEL_WORKERS = '2'
    & $NodePath browser/scripts/build.cjs --complaints-operations
    if ($LASTEXITCODE -ne 0) { throw 'Browser build failed. Review server was not started.' }
    $env:RUN_STAFF_BROWSER_E2E = '1'
    $env:RUN_COMPLAINTS_LOCAL_REVIEW = '1'
    $env:SECRET_KEY = 'synthetic-local-review-only-not-production'
    $env:DJANGO_SECRET_KEY = $env:SECRET_KEY
    $env:DEBUG = 'True'
    $env:SENTRY_DSN = ''
    $env:SENTRY_BROWSER_DSN = ''
    Write-Host 'Preparing isolated review data. Wait for: Local synthetic review ready.'
    & $reviewPython manage.py test staff_auth.local_complaints_review.ComplaintsLocalReview --settings=staff_auth.local_complaints_review_settings --keepdb --noinput --verbosity=0
    if ($LASTEXITCODE -ne 0) { throw 'Local review stopped. Check the error above.' }
} finally {
    foreach ($reviewName in $reviewEnvironment.Keys) { [Environment]::SetEnvironmentVariable($reviewName, $reviewEnvironment[$reviewName], 'Process') }
    Pop-Location
}
