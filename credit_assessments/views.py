"""TAT-authenticated HTTP boundary for governed credit assessment."""

from __future__ import annotations

import json
import io
import logging

from django.conf import settings
from django.http import FileResponse, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from core.api.views import (
    _bind_miniapp_write_request,
    _tat_capability_error,
    _tat_context,
    _tat_payload,
    miniapp_write_response,
)
from core.models import TatTrackerCase

from .models import AssessmentDocument, AssessmentEvent, CreditAssessment, StatementMailReceipt
from .services import (
    AssessmentError,
    bro_review,
    confirm_statement,
    destroy_statement_passcode,
    get_or_create_assessment,
    manager_authorize,
    manager_decide,
    reveal_statement_passcode,
    serialize_assessment,
    statement_candidates,
    submit_analysis,
    submit_pre_appraisal,
    validate_responses,
)


logger = logging.getLogger(__name__)


def _disabled_response():
    return JsonResponse({
        'ok': False,
        'code': 'credit_assessment_disabled',
        'message': 'Credit assessment is not enabled.',
    }, status=404)


def _json_value(payload: dict, key: str, default):
    value = payload.get(key)
    if isinstance(value, (dict, list)):
        return value
    if value in (None, ''):
        return default
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AssessmentError(f'{key.replace("_", " ").title()} is invalid.', code='credit_assessment_payload_invalid') from exc
    if not isinstance(parsed, type(default)):
        raise AssessmentError(f'{key.replace("_", " ").title()} is invalid.', code='credit_assessment_payload_invalid')
    return parsed


def _context(payload: dict):
    group_id, group_config, _user_payload, user, error = _tat_context(payload)
    if error:
        return None, None, None, error
    capability_error = _tat_capability_error(user, 'tat.home.view', group_config)
    if capability_error:
        return None, None, None, capability_error
    case_id = str(payload.get('case_id') or '').strip()
    case = TatTrackerCase.objects.filter(group_id=group_id, case_id=case_id, is_deleted=False).first()
    if not case:
        return None, None, None, JsonResponse({'ok': False, 'message': 'This TAT case was not found.'}, status=404)
    # Reuse the canonical TAT scope check rather than duplicating branch and
    # product policy in this bounded domain.
    from core.services.tat_tracker import get_case_detail
    try:
        get_case_detail(group_config, user, case_id)
    except ValueError as exc:
        return None, None, None, JsonResponse({'ok': False, 'message': str(exc)}, status=403)
    return case, user, group_config, None


def _projection(assessment: CreditAssessment, user: dict) -> dict:
    data = serialize_assessment(assessment, user)
    if assessment.state in {assessment.STATE_DRAFT, assessment.STATE_RETURNED_PRE_ANALYSIS}:
        data['statement_candidates'] = [
            {
                'id': str(item.pk),
                'filename': item.attachment_name,
                'customer_name': item.customer_name,
                'period_start': item.statement_period_start.isoformat() if item.statement_period_start else '',
                'period_end': item.statement_period_end.isoformat() if item.statement_period_end else '',
                'full_year': item.statement_full_year,
                'received_at': item.inbox_received_at.isoformat(),
            }
            for item in statement_candidates(assessment, user)
        ]
    return data


@csrf_exempt
@require_http_methods(['POST'])
@miniapp_write_response
def credit_assessment_detail(request):
    if not bool(getattr(settings, 'CREDIT_ASSESSMENT_GMAIL_ENABLED', False)):
        return _disabled_response()
    payload = _tat_payload(request)
    case, user, _group_config, error = _context(payload)
    if error:
        return error
    assessment = CreditAssessment.objects.filter(tat_case=case).first()
    return JsonResponse({'ok': True, 'data': None if not assessment else _projection(assessment, user)})


@csrf_exempt
@require_http_methods(['POST'])
@miniapp_write_response
def credit_assessment_action(request):
    if not bool(getattr(settings, 'CREDIT_ASSESSMENT_GMAIL_ENABLED', False)):
        return _disabled_response()
    payload = _tat_payload(request)
    key_error = _bind_miniapp_write_request(request, payload)
    if key_error:
        return key_error
    case, user, _group_config, error = _context(payload)
    if error:
        return error
    action = str(payload.get('action') or '').strip()
    request_id = str(payload.get('request_id') or request.headers.get('X-Request-ID') or '').strip()
    assessment = CreditAssessment.objects.filter(tat_case=case).first()
    try:
        if action == 'start':
            assessment = get_or_create_assessment(case=case, user=user, request_id=request_id)
        elif not assessment:
            raise AssessmentError('Start the credit assessment first.', code='credit_assessment_not_started', status=404)
        elif action == 'confirm_statement':
            assessment = confirm_statement(
                assessment=assessment, receipt_id=payload.get('receipt_id'), user=user,
                expected_revision=payload.get('revision'), request_id=request_id,
            )
        elif action == 'submit_pre_appraisal':
            assessment = submit_pre_appraisal(
                assessment=assessment, user=user, expected_revision=payload.get('revision'), request_id=request_id,
                pre_appraisal_file=request.FILES.get('pre_appraisal'),
                signed_laf_reference=payload.get('signed_laf_reference'),
                signed_laf_hash=payload.get('signed_laf_hash'), passcode=payload.get('passcode'),
            )
        elif action == 'authorize':
            assessment = manager_authorize(
                assessment=assessment, user=user, expected_revision=payload.get('revision'), request_id=request_id,
                action=payload.get('decision'), comment=payload.get('comment'),
            )
        elif action == 'submit_analysis':
            assessment = submit_analysis(
                assessment=assessment, user=user, expected_revision=payload.get('revision'), request_id=request_id,
                analysis_file=request.FILES.get('analysis_report'), spin_file=request.FILES.get('spin_report'),
                crb_file=request.FILES.get('crb_report'), questions=_json_value(payload, 'questions', []),
            )
        elif action == 'bro_review':
            assessment = bro_review(
                assessment=assessment, user=user, expected_revision=payload.get('revision'), request_id=request_id,
                responses=_json_value(payload, 'responses', {}),
            )
        elif action == 'validate_responses':
            assessment = validate_responses(
                assessment=assessment, user=user, expected_revision=payload.get('revision'), request_id=request_id,
                outcomes=_json_value(payload, 'outcomes', {}),
            )
        elif action == 'decide':
            assessment = manager_decide(
                assessment=assessment, user=user, expected_revision=payload.get('revision'), request_id=request_id,
                action=payload.get('decision'), comment=payload.get('comment'),
            )
        elif action == 'reveal_passcode':
            value = reveal_statement_passcode(assessment, user, request_id)
            return JsonResponse({'ok': True, 'data': _projection(assessment, user), 'passcode': value})
        elif action == 'destroy_passcode':
            assessment = destroy_statement_passcode(assessment, user, request_id)
        else:
            raise AssessmentError('Choose a valid credit-assessment action.', code='credit_assessment_action_invalid')
    except AssessmentError as exc:
        return JsonResponse({'ok': False, 'code': exc.code, 'message': str(exc)}, status=exc.status)
    return JsonResponse({'ok': True, 'data': _projection(assessment, user)})


@csrf_exempt
@require_http_methods(['POST'])
def credit_assessment_document(request):
    """Stream protected evidence only after current TAT scope authorization."""
    if not bool(getattr(settings, 'CREDIT_ASSESSMENT_GMAIL_ENABLED', False)):
        return _disabled_response()
    payload = _tat_payload(request)
    case, user, _group_config, error = _context(payload)
    if error:
        return error
    assessment = CreditAssessment.objects.filter(tat_case=case).first()
    if not assessment:
        return JsonResponse({'ok': False, 'message': 'Credit assessment was not found.'}, status=404)
    roles = {str(value or '').strip().upper() for value in (user.get('roles') or [])}
    if not roles.intersection({'BRO', 'BM', 'CA', 'CREDIT_ANALYST', 'IT'}):
        return JsonResponse({'ok': False, 'message': 'Your assigned role cannot open credit-assessment evidence.'}, status=403)
    source = str(payload.get('source') or 'document')
    mode = str(payload.get('mode') or 'preview').strip().casefold()
    if mode not in {'preview', 'download'}:
        return JsonResponse({'ok': False, 'message': 'Choose preview or download.'}, status=400)
    item_id = str(payload.get('document_id') or '')
    if source == 'statement':
        item = StatementMailReceipt.objects.filter(pk=item_id, linked_assessments=assessment).first()
        drive_file_id = item.drive_file_id if item else ''
        filename = item.attachment_name if item else ''
    else:
        item = AssessmentDocument.objects.filter(pk=item_id, assessment=assessment).first()
        drive_file_id = item.drive_file_id if item else ''
        filename = item.original_filename if item else ''
    if not item or not drive_file_id:
        return JsonResponse({'ok': False, 'message': 'This evidence file is unavailable.'}, status=404)
    try:
        from core.services.order_approval import GoogleDriveMediaStorage
        storage = GoogleDriveMediaStorage(request_timeout=60)
        content = storage.download(drive_file_id)
    except Exception as exc:
        logger.warning(
            'Credit assessment evidence read failed: source=%s code=%s',
            source, type(exc).__name__,
        )
        return JsonResponse({'ok': False, 'message': 'The evidence file could not be opened. Try again or contact IT.'}, status=502)
    if mode == 'preview':
        try:
            from core.services.secure_media_preview import pdf_preview_html
            password = str(payload.get('passcode') or '').strip()
            if source == 'statement' and not password:
                from .services import statement_passcode_for_preview
                password = statement_passcode_for_preview(assessment, user)
            preview = pdf_preview_html(
                content,
                filename or 'Credit assessment evidence',
                password=password or None,
                show_filename=False,
            )
        except AssessmentError as exc:
            return JsonResponse({'ok': False, 'code': exc.code, 'message': str(exc)}, status=exc.status)
        except Exception:
            message = (
                'Enter the M-PESA statement passcode, then try Preview again.'
                if source == 'statement' else
                'This PDF could not be previewed. Download it to open it on your device.'
            )
            return JsonResponse({'ok': False, 'message': message}, status=422)
        response = HttpResponse(preview, content_type='text/html; charset=utf-8')
        response['Content-Disposition'] = 'inline'
    else:
        response = FileResponse(
            io.BytesIO(content), content_type='application/pdf',
            as_attachment=True, filename=filename,
        )
    request_id = str(request.headers.get('X-Request-ID') or '').strip()
    if request_id:
        AssessmentEvent.objects.get_or_create(
            assessment=assessment, request_id=request_id,
            defaults={
                'action': f'evidence.{"previewed" if mode == "preview" else "downloaded"}',
                'revision': assessment.revision,
                'actor': user.get('_canonical_user'),
                'metadata': {
                    'document_type': item.document_type if source != 'statement' else 'mpesa_statement',
                },
            },
        )
    response['Cache-Control'] = 'private, no-store'
    return response
