"""Telegram-authenticated Portal endpoints using existing scoped correction authority."""
import json
from django.core.exceptions import PermissionDenied, ObjectDoesNotExist, ValidationError
from django.db import IntegrityError
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from core.api.portal_views import portal_auth_required
from core.models import GroupSheetConfiguration
from . import services
from .models import LegacyBatch, LegacyRow


def identity(request):
    return getattr(request, 'portal_user', None) or request.user, getattr(request, 'portal_access', None)


@csrf_exempt
@portal_auth_required
def workspace(request, batch_id=None, row_id=None):
    actor, access = identity(request)
    try:
        if request.method == 'GET' and not batch_id:
            groups = []
            for group in GroupSheetConfiguration.objects.filter(enabled=True):
                if str((group.workflow or {}).get('type', '')) not in {'jawabu', 'jawabu_homebiogas'}: continue
                try: services.authorize(actor, access, group)
                except PermissionDenied: continue
                groups.append({'id': str(group.pk), 'label': group.display_name or group.sheet_name})
            ids = [g['id'] for g in groups]
            batches = [{'id': str(b.pk), 'namespace': b.namespace, 'group_id': str(b.group_id)} for b in LegacyBatch.objects.filter(group_id__in=ids).order_by('-created_at')[:100]]
            return JsonResponse({'ok': True, 'groups': groups, 'batches': batches})
        if request.method == 'GET' and batch_id:
            batch = LegacyBatch.objects.select_related('group').get(pk=batch_id)
            services.authorize(actor, access, batch.group)
            start = max(0, int(request.GET.get('offset', 0)))
            from core.services.workflow_access import scope_workflow_queryset
            scoped = scope_workflow_queryset(batch.rows.all(), actor, 'jawabu_portal', 'portal.case.correct',
                access=access, branch_field='values__branch', product_field='values__payment_product',
                group_field='batch__group__group_id')
            rows = list(scoped.select_related('batch__group', 'farmer').order_by('source_sheet', 'source_row')[start:start+50])
            for row in rows:
                services.authorize(actor, access, batch.group, branch=row.values.get('branch', ''), product=row.values.get('payment_product', ''))
                if row.farmer_id: services.authorize(actor, access, batch.group, farmer=row.farmer)
            return JsonResponse({'ok': True, 'id': str(batch.pk), 'rows': [services.row_payload(r) for r in rows],
                                 'total': scoped.count(), 'committed': scoped.filter(committed_at__isnull=False).count(), 'offset': start})
        if request.method != 'POST': return JsonResponse({'ok': False, 'error': 'Method not allowed.'}, status=405)
        if request.FILES:
            group = GroupSheetConfiguration.objects.get(pk=request.POST.get('group_id'), enabled=True)
            if str((group.workflow or {}).get('type', '')) not in {'jawabu', 'jawabu_homebiogas'}: raise ValueError('Choose a Portal group.')
            upload = request.FILES.get('file')
            if not upload or upload.size > 20*1024*1024: raise ValueError('Select one XLSX workbook up to 20 MB.')
            batch = services.stage(upload.read(), namespace=request.POST.get('namespace', ''), group=group, actor=actor, access=access)
            return JsonResponse({'ok': True, 'id': str(batch.pk)})
        body = json.loads(request.body or '{}')
        if not isinstance(body, dict): raise ValueError('A JSON object is required.')
        if row_id:
            row = services.confirm_stage(row_id, state=body.get('state'), note=body.get('note'),
                expected_revision=body.get('revision'), request_key=body.get('request_id'), actor=actor, access=access)
            return JsonResponse({'ok': True, 'row': services.row_payload(row)})
        batch = LegacyBatch.objects.select_related('group').get(pk=batch_id)
        services.authorize(actor, access, batch.group)
        selected = body.get('rows', [])
        if not isinstance(selected, list) or not 1 <= len(selected) <= 50: raise ValueError('Select 1–50 reviewed rows per commit.')
        if not body.get('request_id') or len(str(body['request_id'])) > 80: raise ValueError('A bounded request ID is required.')
        results = []
        for item in selected:
            if not isinstance(item, dict): raise ValueError('Each row selection must be an object.')
            row = batch.rows.get(pk=item['id'])
            services.authorize(actor, access, batch.group, branch=row.values.get('branch', ''), product=row.values.get('payment_product', ''))
            try:
                result = services.commit_row(row.pk, expected_revision=item.get('revision'),
                    request_key=str(body.get('request_id', ''))+':'+str(row.pk), actor=actor, access=access,
                    existing_case_id=item.get('existing_case_id', ''), separate_unit_note=item.get('note', ''))
                results.append({'id': str(row.pk), 'ok': True, 'farmer_id': str(result.farmer_id)})
            except (ValueError, IntegrityError) as exc:
                results.append({'id': str(row.pk), 'ok': False, 'error': str(exc) if isinstance(exc, ValueError) else 'Existing case/source collision: refresh and reconcile explicitly.'})
        return JsonResponse({'ok': True, 'results': results})
    except PermissionDenied as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=403)
    except ObjectDoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Import record not found in this workspace.'}, status=404)
    except (ValueError, TypeError, KeyError, IntegrityError, ValidationError) as exc:
        # Return only controlled validation text, never database details or raw workbook data.
        detail = str(exc) if isinstance(exc, ValueError) else 'Invalid import request or conflicting source identity.'
        return JsonResponse({'ok': False, 'code': 'legacy_import_invalid', 'error': detail, 'legacy_detail': detail}, status=400)
