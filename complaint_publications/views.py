from django.http import JsonResponse

from core.api.browser_complaint_operations import endpoint, payload
from core.services.complaint_cases import ComplaintCaseError
from . import services


@endpoint(['POST'])
def reserve(request, group, actor):
    body = payload(request)
    if set(body) != {'path', 'fields', 'files'} or not isinstance(body['path'], str):
        raise ComplaintCaseError('Review the upload request.')
    attempt = services.reserve(group, actor, body['path'], body['fields'], body['files'])
    return JsonResponse(services.attempt_state(attempt))


@endpoint(['GET'])
def progress(request, group, actor, attempt_key):
    return JsonResponse(services.attempt_state(services.owned_attempt(group, actor, attempt_key)))


@endpoint(['PUT'])
def receive(request, group, actor, attempt_key, file_key):
    return JsonResponse(services.file_state(services.receive(group, actor, attempt_key, file_key, request)))


@endpoint(['GET'])
def attention(request, group, actor):
    return JsonResponse({'items': services.attention(group, actor)})


@endpoint(['GET'])
def case_progress(request, group, actor, case_key):
    from core.models import ParsedMessage
    from django.core.exceptions import PermissionDenied
    case = ParsedMessage.objects.filter(pk=case_key, group_id=group.group_id).first()
    if not case:
        raise PermissionDenied
    return JsonResponse(services.case_state(group, actor, case))
