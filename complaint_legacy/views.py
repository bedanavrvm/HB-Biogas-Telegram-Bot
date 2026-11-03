"""Separate signed-Telegram and native cookie/CSRF adapters over one importer."""
import base64
import binascii
import json
import shutil
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.db import IntegrityError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from core.api.complaint_case_views import _context, _request_payload, miniapp_write_response
from core.api.browser_complaint_operations import endpoint, payload as browser_payload
from core.services import complaint_cases as cases
from . import services, workbook
from .models import ImportUpload


def command(request,group,actor,body,upload_id=None,action='index'):
    try:
        if not isinstance(body,dict): raise ValueError('A JSON object is required.')
        owner=services.authorize(group,actor)
        if action=='template':
            response=HttpResponse(workbook.template(),content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
            response['Content-Disposition']='attachment; filename="Complaints - Legacy Import Template.xlsx"'
            return response
        if upload_id is None:
            if request.method=='GET' or body.get('command')=='index':
                uploads=ImportUpload.objects.filter(group=owner).exclude(phase='discarded').order_by('-created_at')[:50]
                return JsonResponse({'workspace':owner.display_name or owner.sheet_name,'projection_enabled':cases.complaint_sheet_projection_enabled(group),
                    'sheet_name':group.sheet_name,'sheet_id':group.sheet_id,'headers':list(workbook.COMPLAINT_REGISTER_FIELD_HEADERS.values()),
                    'uploads':[services.payload(u) for u in uploads]})
            return JsonResponse({'upload':services.payload(services.create(group,actor,body))})
        upload=ImportUpload.objects.select_related('group').get(pk=upload_id,group=owner)
        if request.method=='GET':
            return JsonResponse({'upload':services.payload(upload),**services.inspect(upload,body.get('offset',0),body.get('filter','all'))})
        with services.leased(upload):
            if action!='chunk' and body.get('revision')!=upload.revision: raise ValueError('This import changed. Refresh saved progress before retrying.')
            if action=='chunk':
                encoded=body.get('content','')
                if not isinstance(encoded,str) or len(encoded)>4*((services.CHUNK+2)//3): raise ValueError('Source chunk exceeds 512 KiB.')
                services.receive(upload,body.get('position'),base64.b64decode(encoded,validate=True))
            elif action=='prepare': services.prepare(upload)
            elif action=='stage':
                if upload.phase!='mapping': raise ValueError('Review the column mapping before staging.')
                upload.phase='staging';services.save(upload)
            elif action=='select': services.select(upload,body)
            elif action=='commit':
                if upload.phase!='ready' or not upload.rows.filter(approved=True,case__isnull=True).exists(): raise ValueError('Approve at least one valid source row before importing.')
                upload.phase='committing';services.save(upload)
            elif action=='publish':
                if upload.phase!='ready' or not upload.rows.filter(case__isnull=False,published=False).exists(): raise ValueError('Save approved cases before requesting publication.')
                if not cases.complaint_sheet_projection_enabled(group): raise ValueError('Enable the existing Complaints Sheet projection before requesting publication.')
                upload.phase='publishing';services.save(upload)
            elif action=='advance':
                if upload.phase=='staging': services.stage_step(upload)
                elif upload.phase=='committing': services.commit_step(upload,group,actor)
                elif upload.phase=='publishing': services.publish_step(upload,group)
                else: raise ValueError('No processing is active. Review the current step.')
            elif action=='discard':
                if upload.rows.filter(committed_at__isnull=False).exists() or upload.phase in {'committing','publishing'}: raise ValueError('Imported case provenance cannot be discarded.')
                upload.rows.all().delete(); upload.chunks.all().delete(); upload.phase='discarded';services.save(upload)
                shutil.rmtree(services.cache_root(upload),ignore_errors=True)
            else: raise ValueError('Unknown import action.')
        return JsonResponse({'upload':services.payload(upload)})
    except PermissionDenied as exc: return JsonResponse({'error':str(exc)},status=403)
    except ObjectDoesNotExist: return JsonResponse({'error':'This import is unavailable in this workspace.'},status=404)
    except (ValueError,TypeError,KeyError,IndexError,IntegrityError,BadZipFile,ParseError,StopIteration,binascii.Error) as exc:
        detail=str(exc) if isinstance(exc,ValueError) else 'Invalid or duplicate source facts. Review this workbook before retrying.'
        return JsonResponse({'error':detail},status=409)


@csrf_exempt
@require_http_methods(['GET','POST'])
@miniapp_write_response
def telegram(request,upload_id=None,action='index'):
    body=_request_payload(request)
    if not isinstance(body,dict): return JsonResponse({'error':'A JSON object is required.'},status=409)
    group,actor,error=_context(request,body)
    if error: return error
    return command(request,group,actor,body,upload_id,action)


@endpoint(['GET','POST'],capability='complaint.legacy.manage')
def browser(request,group,actor,upload_id=None,action='index'):
    body=request.GET.dict() if request.method=='GET' else browser_payload(request)
    return command(request,group,actor,body,upload_id,action)


@require_http_methods(['GET'])
def telegram_page(request):
    return render(request,'complaint_legacy/app.html',{'channel':'telegram','group_id':request.GET.get('group_id','')})


@require_http_methods(['GET'])
def browser_page(request):
    if not settings.STAFF_BROWSER_AUTH_ENABLED or not settings.STAFF_BROWSER_COMPLAINTS_ENABLED: return HttpResponse(status=404)
    from staff_auth.browser_api import require_company_browser_user
    try: require_company_browser_user(request)
    except PermissionDenied: return redirect('/staff/login/')
    return render(request,'complaint_legacy/app.html',{'channel':'browser','group_id':request.GET.get('group','')})
