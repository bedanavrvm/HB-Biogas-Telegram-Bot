"""Explicit IT commands for durable, register-bound cutover sessions."""
import json
from datetime import timedelta
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from zipfile import BadZipFile
from xml.etree.ElementTree import ParseError
from django.core.exceptions import PermissionDenied,ObjectDoesNotExist
from django.core import signing
from django.db import IntegrityError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from gspread.exceptions import APIError
from requests.exceptions import RequestException
from core.api.portal_views import portal_auth_required
from core.models import GroupSheetConfiguration
from core.services.external_resilience import external_call_budget
from . import importer,projection,row_sync,updates
from .models import LegacyUpload
from .registers import SOURCE_SHEETS
from .views import identity


@csrf_exempt
@portal_auth_required
@require_http_methods(['GET','POST'])
def legacy_upload(request,upload_id=None,action='index'):
    actor,access=identity(request)
    try:
        if request.method=='GET' and upload_id is None:
            groups=[]
            for group in GroupSheetConfiguration.objects.filter(enabled=True):
                if (group.workflow or {}).get('type') not in {'jawabu','jawabu_homebiogas'}:continue
                try:importer.authorize(actor,access,group,branch='')
                except PermissionDenied:continue
                groups.append({'id':str(group.pk),'label':group.display_name or group.sheet_name})
            if not groups:raise PermissionDenied('Whole-group Portal IT authority is required.')
            uploads=LegacyUpload.objects.filter(batch__group_id__in=[g['id'] for g in groups]).exclude(phase='discarded')
            if request.GET.get('source_sheet'):
                source=request.GET['source_sheet'];importer.partner_for_source(source);uploads=uploads.filter(source_sheet=source)
            uploads=uploads.select_related('batch__group').order_by('-created_at')[:50]
            return JsonResponse({'ok':True,'groups':groups,'source_sheets':[value for value,label in SOURCE_SHEETS],'uploads':[importer.payload(u) for u in uploads],'superuser':actor.is_superuser})
        if request.method=='POST' and upload_id is None:
            body=json.loads(request.body or '{}')
            if not isinstance(body,dict):raise ValueError('A JSON object is required.')
            upload=importer.create(body,actor,access)
            return JsonResponse({'ok':True,'upload':importer.payload(upload)})
        upload=LegacyUpload.objects.select_related('batch__group').get(pk=upload_id)
        importer.authorize(actor,access,upload.batch.group,branch='')
        if request.method=='GET':
            if request.GET.get('summary')=='1':return JsonResponse({'ok':True,'upload':importer.payload(upload)})
            return JsonResponse({'ok':True,'upload':importer.payload(upload),**importer.inspect_rows(upload,request.GET.get('offset',0),request.GET.get('filter','all'))})
        if request.method!='POST':return JsonResponse({'ok':False,'error':'Method not allowed.'},status=405)
        with importer.leased(upload):
            if action=='chunk':
                if len(request.body)>importer.CHUNK:raise ValueError('Chunk exceeds 512 KiB.')
                importer.receive(upload,request.GET.get('position'),request.body)
            else:
                body=json.loads(request.body or '{}')
                if not isinstance(body,dict):raise ValueError('A JSON object is required.')
                if 'source_sheet' in body and body['source_sheet']!=upload.source_sheet:raise ValueError('This upload is bound to its original register. Create a separate upload for the other sheet.')
                if 'mode' in body and body['mode']!=upload.mode:raise ValueError('Import mode is fixed for this upload.')
                if upload.mode=='updates' and action in {'cleanup_preview','cleanup_confirm','projection_preview','projection_confirm','restart_projection','cancel_preview'}:
                    raise ValueError('Update uploads cannot delete data, replace a register or pause case changes.')
                if action not in {'advance','prepare','cleanup_preview','complete_review'} and body.get('revision')!=upload.revision:raise ValueError('This workspace changed. Refresh saved progress before retrying.')
                if action=='prepare':importer.prepare(upload)
                elif action=='stage':
                    if upload.phase!='mapping':raise ValueError('Preview the column mapping first.')
                    upload.phase='staging';importer.save(upload)
                elif action=='select':importer.select(upload,body);importer.save(upload)
                elif action=='edit':importer.edit(upload,body,actor,access)
                elif action=='complete_review':
                    from .completion import complete_review
                    complete_review(upload,actor=actor,access=access,expected_revision=body.get('revision'),
                        request_key=body.get('request_id'),exceptions=body.get('exceptions'))
                elif action=='cleanup_preview':
                    if upload.phase not in {'ready','deleting'} or upload.drafts.filter(legacy__isnull=False).exists():raise ValueError('Test cleanup must precede canonical imports.')
                    if upload.phase=='deleting':
                        upload.phase='ready'
                        upload.state.pop('cleanup_ids',None)
                    review=importer.cleanup_preview(upload,actor)
                    return JsonResponse({'ok':True,'upload':importer.payload(upload),'review':review})
                elif action=='cleanup_confirm':importer.cleanup_confirm(upload,actor,body.get('token',''))
                elif action=='commit':
                    if upload.phase!='ready' or (upload.mode!='updates' and not upload.state.get('cleanup_complete')):raise ValueError('Complete the review before applying the selection.')
                    upload.phase='committing';importer.save(upload)
                elif action=='sync_rows':
                    if upload.mode=='updates':
                        if upload.phase not in {'ready','committing'}:raise ValueError('Finish the comparison before syncing updates.')
                        upload.state['resume_commit']=upload.phase=='committing';upload.phase='syncing_updates';importer.save(upload)
                    else:row_sync.begin(upload)
                elif action=='recompare':
                    if upload.mode!='updates' or upload.phase!='ready':raise ValueError('Finish processing before refreshing comparisons.')
                    matches=updates.Matches(upload)
                    for draft in upload.drafts.filter(pk__in=body.get('ids',[])[:50]).exclude(reconciliation__applied=True):
                        updates.compare(draft,matches,draft.proposal.get('case_id',''))
                    importer.save(upload)
                elif action=='projection_preview':
                    if upload.phase!='ready':raise ValueError('Finish the current step before previewing replacement.')
                    with external_call_budget(8):preview=projection.preview(upload,actor,access)
                    return JsonResponse({'ok':True,'upload':importer.payload(upload),'preview':preview})
                elif action=='projection_confirm':
                    if upload.phase!='ready' or not upload.frozen:raise ValueError('A held, fully imported cutover is required.')
                    projection.confirm(upload,body)
                elif action=='restart_projection':
                    if upload.phase not in {'backup','projecting','verifying'}:raise ValueError('An uncertain or completed replacement cannot be restarted.')
                    upload.state.setdefault('projection_attempts',[]).append(upload.state.pop('projection'))
                    upload.phase='ready';importer.save(upload)
                elif action=='discard':
                    if upload.frozen or upload.drafts.filter(legacy__isnull=False).exists() or upload.drafts.filter(reconciliation__applied=True).exists():raise ValueError('Saved import/update evidence cannot be discarded.')
                    upload.drafts.all().delete();upload.chunks.all().delete();upload.phase='discarded';importer.save(upload)
                elif action=='cancel_preview':
                    if upload.phase!='ready' or upload.state.get('cleanup_started'):raise ValueError('A started cutover must be completed.')
                    upload.frozen=False
                    for k in list(upload.state):
                        if k.startswith('cleanup_'):upload.state.pop(k)
                    importer.save(upload)
                elif action=='advance':
                    if upload.phase=='staging':importer.stage_step(upload,actor,access)
                    elif upload.phase=='comparing' and upload.mode=='updates':updates.compare_step(upload,actor,access)
                    elif upload.phase=='syncing_updates' and upload.mode=='updates':
                        with external_call_budget(8):result=updates.sync_step(upload,actor,access)
                        return JsonResponse({'ok':True,'upload':importer.payload(upload),**result})
                    elif upload.phase=='deleting':importer.deletion_step(upload,actor)
                    elif upload.phase=='committing':
                        results=importer.commit_step(upload,actor,access)
                        return JsonResponse({'ok':True,'upload':importer.payload(upload),'results':results})
                    elif upload.phase in {'syncing_rows','backup','projecting','verifying','replacing','readback'}:
                        next_at=parse_datetime(upload.state.get('projection_next_at',''))
                        if next_at and next_at>timezone.now():
                            return JsonResponse({'ok':True,'upload':importer.payload(upload),'wait_seconds':(next_at-timezone.now()).total_seconds()})
                        upload.state['projection_next_at']=(timezone.now()+timedelta(seconds=10 if upload.phase=='syncing_rows' else 4)).isoformat()
                        importer.save(upload)
                        try:
                            with external_call_budget(8):
                                if upload.phase=='syncing_rows':row_sync.advance(upload,actor,access)
                                else:projection.advance(upload,actor,access)
                        except (APIError,RequestException,TimeoutError,ValueError) as exc:
                            # Preserve the last confirmed cursor, not in-memory work from a failed step.
                            upload.refresh_from_db()
                            upload.state['sync_error']=str(exc) if isinstance(exc,ValueError) else 'Google Sheets did not confirm this step. Refresh and resume to verify it safely.'
                            importer.save(upload)
                            raise
                        else:
                            if upload.state.pop('sync_error',None):importer.save(upload)
                    else:raise ValueError('Nothing is running. Review the current step.')
                else:raise ValueError('Unknown import action.')
        return JsonResponse({'ok':True,'upload':importer.payload(upload)})
    except PermissionDenied as exc:return JsonResponse({'ok':False,'error':str(exc)},status=403)
    except ObjectDoesNotExist:return JsonResponse({'ok':False,'error':'Import record is unavailable.'},status=404)
    except (APIError,RequestException,TimeoutError):
        detail='Google Sheets did not confirm this step. Saved records and checkpoints remain retained. Refresh progress and resume; replacement is checked before retrying.'
        return JsonResponse({'ok':False,'error':detail,'legacy_detail':detail},status=503)
    except (ValueError,TypeError,IntegrityError,BadZipFile,ParseError,StopIteration,KeyError,IndexError,signing.BadSignature) as exc:
        detail=str(exc) if isinstance(exc,ValueError) else 'Invalid source, changed selection or duplicate source row. Review this upload before retrying.'
        return JsonResponse({'ok':False,'error':detail,'legacy_detail':detail},status=409)
