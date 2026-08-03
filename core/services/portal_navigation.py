"""Server-owned Portal navigation driven by the editable role capability matrix."""

from django.urls import reverse

from core.services.access_policies import BUSINESS_ADMIN_ROLE, OPERATIONS_ADMIN_ROLE


# ``key`` is stable in URLs/client state; the final item is the required
# capability.  This is intentionally one source of truth for sidebar, tabs,
# and direct-screen access checks.
# Stable screen ownership keeps navigation presentation separate from the
# capability that authorizes the route.  The category is deliberately a
# display-only concern: moving an item between sidebar groups must never
# change what a role can read or write.
PORTAL_NAV_ITEMS = (
    ('dashboard', 'Dashboard', 'bar-chart-3', 'portal.dashboard.view'),
    ('jbl', 'JBL Queue', 'home', 'portal.jbl_queue.view'),
    ('my_visits', 'My Visits', 'clipboard-check', 'portal.jbl_followup.view'),
    ('credit', 'Credit', 'shield-check', 'portal.credit_queue.view'),
    ('final', 'Review', 'phone-call', 'portal.final_review.view'),
    ('requisition', 'Orders', 'shopping-bag', 'portal.requisition.view'),
    ('deferred', 'Deferred', 'clock', 'portal.deferred.view'),
    ('all', 'All Cases', 'database', 'portal.case.read'),
    ('case_history', 'Case History', 'route', 'portal.case.read'),
    ('batches', 'Batches', 'layers', 'portal.batches.view'),
    ('invoices', 'Invoices', 'receipt-text', 'portal.invoice.view'),
    ('payments', 'Payments', 'banknote', 'portal.payment.view'),
    ('history', 'Documents', 'history', 'portal.documents.view'),
    ('imports', 'Imports', 'upload', 'portal.imports.view'),
    ('reports', 'Reports', 'chart-no-axes-combined', 'portal.reports.view'),
)

# Personal preferences are available to every already-authorized Portal user.
# They deliberately have no capability code: this is not a second policy
# surface, and a user may only read/write their own preference record.
PORTAL_PERSONAL_NAV_ITEM = ('settings', 'Settings', 'settings')


PORTAL_NAV_CATEGORIES = {
    'dashboard': 'Overview',
    'jbl': 'My work',
    'my_visits': 'My work',
    'credit': 'My work',
    'final': 'My work',
    'requisition': 'My work',
    'batches': 'Finance & documents',
    'invoices': 'Finance & documents',
    'payments': 'Finance & documents',
    'history': 'Finance & documents',
    'all': 'Cases',
    'case_history': 'Cases',
    'deferred': 'Cases',
    'imports': 'IT tools',
    'reports': 'IT tools',
    'settings': 'Account',
}

PORTAL_NAV_CATEGORY_ORDER = (
    'Overview',
    'My work',
    'Finance & documents',
    'Cases',
    'IT tools',
    'Account',
)

# A compact bottom bar is selected from the role's actual scope.  The sidebar
# remains the complete, capability-filtered navigation surface.  This is not
# an authorization decision; a deep link remains guarded by its capability.
BOTTOM_SCREEN_PREFERENCES = (
    ('IT', ('dashboard', 'all', 'imports', 'reports')),
    (BUSINESS_ADMIN_ROLE, ('dashboard', 'final', 'payments', 'all')),
    (OPERATIONS_ADMIN_ROLE, ('dashboard', 'requisition', 'invoices', 'payments')),
    ('HB_STAFF', ('dashboard', 'requisition', 'invoices', 'payments')),
    ('CREDIT_ANALYST', ('dashboard', 'credit', 'all', 'jbl')),
    ('JBL_OFFICER', ('dashboard', 'jbl', 'my_visits', 'requisition')),
)

FALLBACK_BOTTOM_SCREENS = ('dashboard', 'jbl', 'credit', 'final', 'requisition', 'all')


def _bottom_screen_keys(*, roles: set[str], permitted: set[str]) -> set[str]:
    """Return no more than four permitted screens for the mobile bottom bar."""
    capability_by_screen = {key: capability for key, _label, _icon, capability in PORTAL_NAV_ITEMS}
    candidates: list[str] = []
    for role, preferred_screens in BOTTOM_SCREEN_PREFERENCES:
        if role in roles:
            candidates.extend(preferred_screens)
    candidates.extend(FALLBACK_BOTTOM_SCREENS)

    selected: list[str] = []
    for screen in candidates:
        if screen in selected:
            continue
        capability = capability_by_screen.get(screen)
        if capability and capability in permitted:
            selected.append(screen)
        if len(selected) == 4:
            break
    return set(selected)


def get_portal_nav_items(user, *, access=None) -> list[dict]:
    """Return only screens the server says this scoped user may open."""
    # Direct browser loads in a development environment have no Telegram
    # identity; preserve the existing readable shell there without creating
    # a production authorization bypass.
    if user is None and access is None:
        permitted = {item[3] for item in PORTAL_NAV_ITEMS}
    else:
        from core.services.workflow_capabilities import effective_capability_keys

        permitted = effective_capability_keys(user, 'jawabu_portal', access=access)
    roles = {str(role or '').strip().upper() for role in (access or {}).get('roles', []) if str(role or '').strip()}
    bottom_screens = _bottom_screen_keys(roles=roles, permitted=permitted)
    items = [
        {
            'key': key,
            'label': label,
            'icon': icon,
            'url': reverse('portal_screen', kwargs={'screen': key}),
            'capability': capability,
            'category': PORTAL_NAV_CATEGORIES[key],
            'bottom_primary': key in bottom_screens,
        }
        for key, label, icon, capability in PORTAL_NAV_ITEMS
        if capability in permitted
    ]
    # `get_portal_nav_items` is reached only after Portal authentication in
    # production.  In local shell rendering it is harmless and keeps the
    # settings screen discoverable for manual UI checks.
    key, label, icon = PORTAL_PERSONAL_NAV_ITEM
    items.append({
        'key': key,
        'label': label,
        'icon': icon,
        'url': reverse('portal_screen', kwargs={'screen': key}),
        'capability': '',
        'category': PORTAL_NAV_CATEGORIES[key],
        'bottom_primary': False,
    })
    return items


def get_portal_nav_groups(user, *, access=None) -> list[dict]:
    """Group already-authorized Portal destinations for the sidebar only."""
    items = get_portal_nav_items(user, access=access)
    return [
        {
            'label': category,
            'items': [item for item in items if item['category'] == category],
        }
        for category in PORTAL_NAV_CATEGORY_ORDER
        if any(item['category'] == category for item in items)
    ]


def portal_screen_allowed(user, screen: str, *, access=None) -> bool:
    return any(item['key'] == screen for item in get_portal_nav_items(user, access=access))
