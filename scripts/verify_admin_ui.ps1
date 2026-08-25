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

$processEnvironment = [System.Environment]::GetEnvironmentVariables()
$combinedPath = (@($processEnvironment['Path'], $processEnvironment['PATH']) | Where-Object { $_ }) -join ';'
[System.Environment]::SetEnvironmentVariable('PATH', $null, 'Process')
[System.Environment]::SetEnvironmentVariable('Path', $combinedPath, 'Process')

try {
    & "$repository\.venv\Scripts\python.exe" manage.py migrate --noinput | Out-Null
    $seed = "from django.contrib.auth import get_user_model; from core.models import Product,ProductAlias,OriginationDataField,OriginationProductDefinition,OriginationDocumentTemplate,OriginationTemplateConfigurationRevision,OriginationProductDocumentAssignment,GroupSheetConfiguration,AccessGrant,TatEscalationRule,TatResponsibilityAssignment,TatResponsibilityBackup; u=get_user_model().objects.create_superuser('ui-audit-admin','audit@example.test','audit-password'); b=get_user_model().objects.create_user('ui-audit-backup',password='audit-password'); tg=GroupSheetConfiguration.objects.create(group_id='-100-ui-audit-tat',display_name='Synthetic TAT',sheet_id='synthetic-tat-sheet',sheet_name='TRACKER-Business',workflow={'type':'tat_tracker','branches':['Nakuru'],'products':['business']}); AccessGrant.objects.create(user=u,workflow='tat_tracker',role='BRO',branch='Nakuru',group_configuration=tg); AccessGrant.objects.create(user=b,workflow='tat_tracker',role='BRO',branch='Nakuru',group_configuration=tg); er=TatEscalationRule.objects.create(group_configuration=tg,branch='Nakuru',threshold_percent=100,routing_role='RESPONSIBLE_ROLE',approved_by=u); ta=TatResponsibilityAssignment.objects.create(group_configuration=tg,branch='Nakuru',role='BRO',primary_user=u,created_by=u); TatResponsibilityBackup.objects.create(assignment=ta,user=b,rank=1,threshold_percent=100); p=Product.objects.create(name='Synthetic Long-Named Agricultural Asset Finance Product',code='synthetic_audit',category='Asset finance',description='Synthetic description ' * 30); [ProductAlias.objects.create(product=p,alias=f'Synthetic product alias {i} with extended content') for i in range(8)]; f=OriginationDataField.objects.create(key='applicant_name',label='Applicant full legal name',data_type='text',created_by=u); d=OriginationProductDefinition.objects.create(id='00000000-0000-0000-0000-000000000222',product_key='synthetic_origination',name='Synthetic Origination Product',version=1,document_type='synthetic_origination_laf',form_schema={'sections':[{'key':'applicant','label':'Applicant','help_text':'Synthetic applicant fields'}],'fields':[{'data_field_id':str(f.pk),'key':f.key,'label':f.label,'type':'text','section_key':'applicant','required':True,'width':'half'}]},signer_rules=[{'role':'borrower','required':True,'slots':[{'key':'signature','label':'Borrower signature','type':'signature','required':True}]}],created_by=u); c={'field_overlay_manifest':{'fields':{'applicant_name':{'context_key':'applicant_name','units':'pt','page_number':1,'box':{'x':100,'y':610,'width':180,'height':30},'allowed_area':{'x':100,'y':610,'width':180,'height':30}}}},'signature_overlay_manifest':{'slots':{}},'sample_context':{}}; t=OriginationDocumentTemplate.objects.create(id='00000000-0000-0000-0000-000000000111',product_definition=d,document_type=d.document_type,name='Synthetic LAF Template',version=1,status='ready',source_filename='synthetic.pdf',source_sha256='a'*64,source_byte_size=1024,page_count=1,placement_config=c,drive_file_id='synthetic-drive-id',created_by=u); OriginationTemplateConfigurationRevision.objects.create(template=t,revision=1,configuration=c,created_by=u); g=OriginationDocumentTemplate.objects.create(id='00000000-0000-0000-0000-000000000333',product_definition=None,document_key='home_visit',document_role='supporting',document_type='home_visit',name='Synthetic Home Visit',version=2,status='active',source_filename='home-visit.pdf',source_sha256='b'*64,source_byte_size=1024,page_count=1,placement_config=c,drive_file_id='synthetic-shared-drive-id',form_schema={'fields':[{'key':'applicant_name','label':'Applicant name','type':'text','required':True}]},created_by=u); gr=OriginationTemplateConfigurationRevision.objects.create(template=g,revision=1,configuration=c,is_published=True,created_by=u); g.published_configuration_revision=gr; g.save(update_fields=['published_configuration_revision']); OriginationProductDocumentAssignment.objects.create(id='00000000-0000-0000-0000-000000000444',product_definition=d,template=g,document_key='home_visit',name='Home Visit Form',version_policy='latest_compatible',inclusion_mode='required',created_by=u)"
    & "$repository\.venv\Scripts\python.exe" manage.py shell -c $seed
    $primarySeed = "from django.contrib.auth import get_user_model; from core.models import OriginationDocumentTemplate,OriginationTemplateConfigurationRevision; u=get_user_model().objects.get(username='ui-audit-admin'); t=OriginationDocumentTemplate.objects.create(product_definition=None,document_key='primary',document_role='primary',inclusion_mode='required',display_order=0,document_type='synthetic_reusable_primary',name='Synthetic Reusable Primary LAF',version=1,status='active',source_filename='reusable-primary.pdf',source_sha256='c'*64,source_byte_size=1024,page_count=1,placement_config={},drive_file_id='synthetic-reusable-primary-drive-id',form_schema={'sections':[{'key':'applicant','label':'Applicant'}],'fields':[]},signer_rules=[],created_by=u); r=OriginationTemplateConfigurationRevision.objects.create(template=t,revision=1,configuration={},is_published=True,created_by=u); t.published_configuration_revision=r; t.save(update_fields=['published_configuration_revision'])"
    & "$repository\.venv\Scripts\python.exe" manage.py shell -c $primarySeed
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
    if ($server -and -not $server.HasExited) {
        Stop-Process -Id $server.Id -Force
        $server.WaitForExit(5000) | Out-Null
    }
    if (Test-Path -LiteralPath $auditDatabase) {
        for ($cleanupAttempt = 0; $cleanupAttempt -lt 10; $cleanupAttempt++) {
            try { Remove-Item -LiteralPath $auditDatabase -Force -ErrorAction Stop; break }
            catch {
                if ($cleanupAttempt -eq 9) { Write-Warning "Could not remove temporary audit database: $auditDatabase" }
                else { Start-Sleep -Milliseconds 150 }
            }
        }
    }
}
