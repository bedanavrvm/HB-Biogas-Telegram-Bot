"""Server-owned, capability-filtered Portal pipeline navigation."""

from django.urls import reverse


# Public screen keys, routes and capabilities are deliberately unchanged. The
# presentation metadata can regroup work without becoming a second policy.
PORTAL_NAV_ITEMS = (
    ('dashboard', 'Home', 'house', 'portal.dashboard.view'),
    ('jbl', 'Visit Queue', 'map-pinned', 'portal.jbl_queue.view'),
    ('my_visits', 'My Submitted Visits', 'clipboard-check', 'portal.jbl_followup.view'),
    ('credit', 'Credit Analysis', 'shield-check', 'portal.credit_queue.view'),
    ('final', 'Final Approval', 'badge-check', 'portal.final_review.view'),
    ('requisition', 'Order Preparation', 'shopping-bag', 'portal.requisition.view'),
    ('deferred', 'Deferred & Reappraisal', 'clock', 'portal.deferred.view'),
    ('all', 'All Cases', 'database', 'portal.case.read'),
    ('case_history', 'Case History', 'route', 'portal.case.read'),
    ('batches', 'Finalized Orders', 'layers', 'portal.batches.view'),
    ('invoices', 'Invoice Review', 'receipt-text', 'portal.invoice.view'),
    ('payments', 'Payment Preparation', 'banknote', 'portal.payment.view'),
    ('history', 'Document Archive', 'archive', 'portal.documents.view'),
    ('farmup', 'FarmUp Worklists', 'file-up', 'portal.farmup.view'),
    ('imports', 'Import History', 'upload', 'portal.imports.view'),
    ('reports', 'Reports', 'chart-no-axes-combined', 'portal.reports.view'),
)

PORTAL_PERSONAL_NAV_ITEM = ('settings', 'Settings', 'settings')

PIPELINE_STAGES = (
    ('intake', 'Intake', 'inbox', ('farmup', 'imports')),
    ('visit', 'Field Visit', 'map-pinned', ('jbl', 'my_visits')),
    ('credit', 'Credit', 'shield-check', ('credit',)),
    ('approval', 'Approval', 'badge-check', ('final',)),
    ('fulfilment', 'Fulfilment', 'package-check', ('requisition', 'batches')),
    ('finance', 'Finance', 'banknote', ('invoices', 'payments', 'history')),
)

PORTAL_SCREEN_PRESENTATION = {
    'dashboard': {'hub': 'home', 'group': 'Home', 'order': 0},
    'farmup': {'hub': 'pipeline', 'stage': 'intake', 'group': 'Pipeline · Intake', 'order': 0},
    'imports': {'hub': 'pipeline', 'stage': 'intake', 'group': 'Pipeline · Intake', 'order': 1},
    'jbl': {'hub': 'pipeline', 'stage': 'visit', 'group': 'Pipeline · Field Visit', 'order': 0},
    'my_visits': {'hub': 'pipeline', 'stage': 'visit', 'group': 'Pipeline · Field Visit', 'order': 1},
    'credit': {'hub': 'pipeline', 'stage': 'credit', 'group': 'Pipeline · Credit', 'order': 0},
    'final': {'hub': 'pipeline', 'stage': 'approval', 'group': 'Pipeline · Approval', 'order': 0},
    'requisition': {'hub': 'pipeline', 'stage': 'fulfilment', 'group': 'Pipeline · Fulfilment', 'order': 0},
    'batches': {'hub': 'pipeline', 'stage': 'fulfilment', 'group': 'Pipeline · Fulfilment', 'order': 1},
    'invoices': {'hub': 'pipeline', 'stage': 'finance', 'group': 'Pipeline · Finance', 'order': 0},
    'payments': {'hub': 'pipeline', 'stage': 'finance', 'group': 'Pipeline · Finance', 'order': 1},
    'history': {'hub': 'pipeline', 'stage': 'finance', 'group': 'Pipeline · Finance', 'order': 2},
    'all': {'hub': 'cases', 'group': 'Cases', 'order': 0},
    'deferred': {'hub': 'cases', 'group': 'Cases', 'order': 1},
    'case_history': {'hub': 'cases', 'group': 'Cases', 'order': 2},
    'reports': {'hub': 'more', 'group': 'More', 'order': 0},
    'settings': {'hub': 'more', 'group': 'More', 'order': 1},
}

PORTAL_NAV_GROUP_ORDER = (
    'Home', 'Pipeline · Intake', 'Pipeline · Field Visit', 'Pipeline · Credit',
    'Pipeline · Approval', 'Pipeline · Fulfilment', 'Pipeline · Finance', 'Cases', 'More',
)

PORTAL_HUBS = (
    ('home', 'Home', 'house'),
    ('pipeline', 'Pipeline', 'git-branch'),
    ('cases', 'Cases', 'folder-search'),
    ('more', 'More', 'menu'),
)
PIPELINE_STAGE_ORDER = {stage[0]: index for index, stage in enumerate(PIPELINE_STAGES)}


def portal_screen_presentation(screen: str) -> dict:
    """Return display-only ownership for a stable Portal screen key."""
    return dict(PORTAL_SCREEN_PRESENTATION.get(screen, {'hub': 'more', 'group': 'More', 'order': 99}))


def _permitted_capabilities(user, access) -> set[str]:
    if user is None and access is None:
        return {item[3] for item in PORTAL_NAV_ITEMS}
    from core.services.workflow_capabilities import effective_capability_keys
    return effective_capability_keys(user, 'jawabu_portal', access=access)


def get_portal_nav_items(user, *, access=None) -> list[dict]:
    """Return only screens the server says this scoped user may open."""
    permitted = _permitted_capabilities(user, access)
    items = []
    for key, label, icon, capability in PORTAL_NAV_ITEMS:
        if capability not in permitted:
            continue
        presentation = portal_screen_presentation(key)
        items.append({
            'key': key, 'label': label, 'icon': icon,
            'url': reverse('portal_screen', kwargs={'screen': key}),
            'capability': capability, 'category': presentation['group'],
            'hub': presentation['hub'], 'stage': presentation.get('stage', ''),
            'order': presentation['order'],
            # Compatibility for API/settings consumers; the bottom surface is
            # now rendered from stable hub records.
            'bottom_primary': presentation['hub'] == 'home',
        })

    key, label, icon = PORTAL_PERSONAL_NAV_ITEM
    presentation = portal_screen_presentation(key)
    items.append({
        'key': key, 'label': label, 'icon': icon,
        'url': reverse('portal_screen', kwargs={'screen': key}),
        'capability': '', 'category': presentation['group'],
        'hub': presentation['hub'], 'stage': '', 'order': presentation['order'],
        'bottom_primary': False,
    })
    return items


def get_portal_nav_groups(user, *, access=None) -> list[dict]:
    """Group authorized destinations in pipeline order for the drawer."""
    items = get_portal_nav_items(user, access=access)
    return [
        {'label': group, 'items': [item for item in items if item['category'] == group]}
        for group in PORTAL_NAV_GROUP_ORDER
        if any(item['category'] == group for item in items)
    ]


def get_portal_nav_hubs(user, *, access=None, active_screen: str = 'dashboard') -> list[dict]:
    """Return no more than four stable mobile hubs with authorized landings."""
    items = get_portal_nav_items(user, access=access)
    active_hub = portal_screen_presentation(active_screen)['hub']
    hubs = []
    for key, label, icon in PORTAL_HUBS:
        candidates = sorted(
            (item for item in items if item['hub'] == key),
            key=lambda item: (
                PIPELINE_STAGE_ORDER.get(item.get('stage', ''), 99),
                item.get('order', 99),
                item['key'],
            ),
        )
        if not candidates:
            continue
        landing = candidates[0]
        hubs.append({
            'key': key, 'label': label, 'icon': icon, 'url': landing['url'],
            'screen': landing['key'],
            'screens': ' '.join(item['key'] for item in candidates),
            'active': key == active_hub,
        })
    return hubs


def get_portal_pipeline_stages(user, *, access=None, active_screen: str = '') -> list[dict]:
    """Return the actor's accessible pipeline stages in canonical order."""
    items = get_portal_nav_items(user, access=access)
    active_stage = portal_screen_presentation(active_screen).get('stage', '')
    stages = []
    for key, label, icon, _screen_order in PIPELINE_STAGES:
        stage_items = sorted(
            (item for item in items if item.get('stage') == key),
            key=lambda item: (item.get('order', 99), item['key']),
        )
        if not stage_items:
            continue
        stages.append({
            'key': key, 'label': label, 'icon': icon,
            'url': stage_items[0]['url'], 'screen': stage_items[0]['key'],
            'screens': ' '.join(item['key'] for item in stage_items),
            'active': key == active_stage, 'items': stage_items,
        })
    return stages


def portal_screen_allowed(user, screen: str, *, access=None) -> bool:
    return any(item['key'] == screen for item in get_portal_nav_items(user, access=access))
