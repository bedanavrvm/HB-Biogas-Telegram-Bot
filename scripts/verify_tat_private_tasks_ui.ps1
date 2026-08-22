param(
    [string]$BaseUrl = 'http://127.0.0.1:8765/api/tat-tracker/?group_id=-100-synthetic'
)

$ErrorActionPreference = 'Stop'
$repoRoot = Split-Path -Parent $PSScriptRoot
$auditRoot = Join-Path ([System.IO.Path]::GetTempPath()) 'hb-origination-playwright'
$outputRoot = Join-Path ([System.IO.Path]::GetTempPath()) 'hb-tat-private-task-audit'

if (-not (Test-Path (Join-Path $auditRoot 'node_modules\playwright'))) {
    npm.cmd install --prefix $auditRoot playwright@1.62.1 --no-save --no-audit --no-fund
}

$env:NODE_PATH = Join-Path $auditRoot 'node_modules'
$env:TAT_AUDIT_URL = $BaseUrl
$env:TAT_AUDIT_OUTPUT = $outputRoot
node (Join-Path $repoRoot 'scripts\tat_private_tasks_visual_audit.js')
