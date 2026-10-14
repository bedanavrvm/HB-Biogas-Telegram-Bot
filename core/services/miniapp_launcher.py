"""Read-only app discovery. Every destination retains its own authorization."""
from urllib.parse import urlencode
from django.conf import settings
from django.urls import reverse
from core.models import GroupSheetConfiguration
from core.services.staff_telegram_onboarding import launcher_capability_candidates
from core.services.telegram_identity import user_access
from core.services.telegram_launchers import build_launcher_url
from core.services.workflow_access import workflow_access_decision


APPS = (
    ('tat_tracker', 'tat_tracker', 'TAT Tracker', 'Loan stages and turnaround', ('tat_tracker',)),
    ('complaint_cases', 'complaint_cases', 'Complaints', 'Report and follow up complaints', ('case',)),
    ('pipeline_portal', 'jawabu_portal', 'Portal', 'Visits, orders and payments', ('jawabu', 'jawabu_homebiogas')),
    ('loan_origination', 'loan_origination', 'Origination', 'Loan applications and signatures', ('loan_origination',)),
)


def available_apps(user):
    if not user or not user.is_active:
        return []
    groups = list(GroupSheetConfiguration.objects.filter(enabled=True).order_by('display_name', 'group_id'))
    result = []
    for key, workflow, label, description, group_types in APPS:
        access = user_access(user, workflow)
        capabilities = launcher_capability_candidates(key)
        if not any(workflow_access_decision(user, workflow, capability, access=access).allowed
                   for capability in capabilities):
            continue
        destinations = []
        for group in groups:
            if (group.workflow or {}).get('type') not in group_types:
                continue
            if not any(workflow_access_decision(user, workflow, capability, access=access,
                                               group_configuration=group).allowed for capability in capabilities):
                continue
            url = build_launcher_url(key, group.group_id)
            if not url and key == 'tat_tracker':
                base = str(getattr(settings, 'APP_BASE_URL', '') or '').rstrip('/')
                url = base + reverse('tat_tracker_app') + '?' + urlencode({'group_id':group.group_id})
            if url and not any(item['url'] == url for item in destinations):
                destinations.append({'label': group.display_name or label, 'url': url})
        # These apps have their own current-scope landing/group selector. Never
        # invent a group ID for TAT/Complaints, which require an explicit launch.
        if not destinations and key in {'pipeline_portal', 'loan_origination'}:
            url = build_launcher_url(key, '')
            if url:
                destinations.append({'label': label, 'url': url})
        if destinations:
            result.append({'key': key, 'label': label, 'description': description, 'destinations': destinations})
    return result
