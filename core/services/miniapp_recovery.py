"""Presentation only. Authorization and repairs belong to each workflow."""
from django.core.paginator import Paginator
from django.http import JsonResponse


def status_response(payload):
    response = JsonResponse({'ok': True, 'data': payload})
    response['Cache-Control'] = 'private, no-store, max-age=0'
    return response


def page_payload(rows, page=1):
    result = Paginator(rows, 10).get_page(page)
    return {
        'items': list(result),
        'pagination': {'page': result.number, 'pages': result.paginator.num_pages,
                       'total': result.paginator.count},
    }


def issue(key, title, *, detail, status='Needs review', action=None, reference='', steps=None):
    return {'key': str(key), 'title': title, 'detail': detail, 'status': status,
            'action': action, 'reference': str(reference or key), 'steps': steps or [
                'Ask your app administrator to check this update using the support reference.',
                'Your saved record is unchanged. Do not submit it again.',
            ]}


def request_action(label, endpoint, payload, confirmation):
    return {'label': label, 'endpoint': endpoint, 'payload': payload, 'confirmation': confirmation}


def configuration_failure(code):
    """Known setup failures need a repair before another provider attempt."""
    code = str(code or '').lower()
    return any(part in code for part in (
        'credential', 'permission', 'unauthorized', 'forbidden', 'schema',
        'column', 'not_configured', 'identity_conflict', 'mapping',
    ))
