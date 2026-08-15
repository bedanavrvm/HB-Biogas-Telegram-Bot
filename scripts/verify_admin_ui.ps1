param(
    [int]$Port = 8766,
    [string]$OutputDirectory = "",
    [string]$Viewport = ""
)

$ErrorActionPreference = 'Stop'
$repository = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$auditRoot = Join-Path ([System.IO.Path]::GetTempPath()) 'hb-origination-playwright'
$legacyAuditRoot = Join-Path ([System.IO.Path]::GetTempPath()) 'hb-origination-visual-audit'
$auditDatabase = Join-Path ([System.IO.Path]::GetTempPath()) ('hb-admin-ui-' + [guid]::NewGuid().ToString('N') + '.sqlite3')
if (-not $OutputDirectory) { $OutputDirectory = Join-Path ([System.IO.Path]::GetTempPath()) ('hb-admin-ui-' + [guid]::NewGuid().ToString('N')) }
if (Test-Path (Join-Path $legacyAuditRoot 'node_modules\playwright')) { $auditRoot = $legacyAuditRoot }
else { New-Item -ItemType Directory -Force -Path $auditRoot | Out-Null }
if (-not (Test-Path (Join-Path $auditRoot 'node_modules\playwright'))) {
    npm.cmd install --prefix $auditRoot playwright@1.62.1 --no-save --no-audit --no-fund
}

$env:DEBUG = 'true'
$env:DJANGO_SECRET_KEY = 'synthetic-admin-ui-audit-key'
$env:DATABASE_URL = 'sqlite:///' + ($auditDatabase -replace '\\', '/')
$env:NODE_PATH = Join-Path $auditRoot 'node_modules'
$env:ADMIN_AUDIT_URL = "http://127.0.0.1:$Port"
$env:ADMIN_AUDIT_OUTPUT = $OutputDirectory
if ($Viewport) { $env:ADMIN_AUDIT_VIEWPORT = $Viewport }
else { Remove-Item Env:ADMIN_AUDIT_VIEWPORT -ErrorAction SilentlyContinue }
$stdout = Join-Path $auditRoot 'django-admin-ui-audit.log'
$stderr = Join-Path $auditRoot 'django-admin-ui-audit.err.log'
$server = $null

try {
    & "$repository\.venv\Scripts\python.exe" manage.py migrate --noinput | Out-Null
    $seed = "from django.contrib.auth import get_user_model; from core.models import Product,ProductAlias,OriginationDataField,OriginationProductDefinition,OriginationDocumentTemplate,OriginationTemplateConfigurationRevision; u=get_user_model().objects.create_superuser('ui-audit-admin','audit@example.test','audit-password'); p=Product.objects.create(name='Synthetic Long-Named Agricultural Asset Finance Product',code='synthetic_audit',category='Asset finance',description='Synthetic description ' * 30); [ProductAlias.objects.create(product=p,alias=f'Synthetic product alias {i} with extended content') for i in range(8)]; f=OriginationDataField.objects.create(key='applicant_name',label='Applicant full legal name',data_type='text',created_by=u); d=OriginationProductDefinition.objects.create(id='00000000-0000-0000-0000-000000000222',product_key='synthetic_origination',name='Synthetic Origination Product',version=1,document_type='synthetic_origination_laf',form_schema={'sections':[{'key':'applicant','label':'Applicant','help_text':'Synthetic applicant fields'}],'fields':[{'data_field_id':str(f.pk),'key':f.key,'label':f.label,'type':'text','section_key':'applicant','required':True,'width':'half'}]},signer_rules=[{'role':'borrower','required':True,'slots':[{'key':'signature','label':'Borrower signature','type':'signature','required':True}]}],created_by=u); c={'field_overlay_manifest':{'fields':{'applicant_name':{'context_key':'applicant_name','units':'pt','page_number':1,'box':{'x':100,'y':610,'width':180,'height':30},'allowed_area':{'x':100,'y':610,'width':180,'height':30}}}},'signature_overlay_manifest':{'slots':{}},'sample_context':{}}; t=OriginationDocumentTemplate.objects.create(id='00000000-0000-0000-0000-000000000111',product_definition=d,document_type=d.document_type,name='Synthetic LAF Template',version=1,status='ready',source_filename='synthetic.pdf',source_sha256='a'*64,source_byte_size=1024,page_count=1,placement_config=c,drive_file_id='synthetic-drive-id',created_by=u); OriginationTemplateConfigurationRevision.objects.create(template=t,revision=1,configuration=c,created_by=u)"
    & "$repository\.venv\Scripts\python.exe" manage.py shell -c $seed
    $server = Start-Process -FilePath "$repository\.venv\Scripts\python.exe" -ArgumentList @('manage.py', 'runserver', "127.0.0.1:$Port", '--noreload') -WorkingDirectory $repository -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        try { Invoke-WebRequest -UseBasicParsing "$env:ADMIN_AUDIT_URL/admin/login/" -TimeoutSec 2 | Out-Null; $ready = $true; break }
        catch { Start-Sleep -Milliseconds 500 }
    }
    if (-not $ready) { throw "Django did not become ready. See $stderr" }
    node (Join-Path $repository 'scripts\admin_ui_audit.js')
    if ($LASTEXITCODE -ne 0) { throw "Admin browser audit failed with exit code $LASTEXITCODE" }
} finally {
    if ($server -and -not $server.HasExited) { Stop-Process -Id $server.Id -Force }
    if (Test-Path -LiteralPath $auditDatabase) { Remove-Item -LiteralPath $auditDatabase -Force }
}
