"""Server-owned Portal navigation driven by the editable role capability matrix."""

from django.urls import reverse


# ``key`` is stable in URLs/client state; the final item is the required
# capability.  This is intentionally one source of truth for sidebar, tabs,
# and direct-screen access checks.
PORTAL_NAV_ITEMS = (
    ('dashboard', 'Dashboard', 'bar-chart-3', 'portal.dashboard.view'),
    ('jbl', 'JBL Queue', 'home', 'portal.jbl_queue.view'),
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
)

# Personal preferences are available to every already-authorized Portal user.
# They deliberately have no capability code: this is not a second policy
# surface, and a user may only read/write their own preference record.
PORTAL_PERSONAL_NAV_ITEM = ('settings', 'Settings', 'settings')


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
    items = [
        {
            'key': key,
            'label': label,
            'icon': icon,
            'url': reverse('portal_screen', kwargs={'screen': key}),
            'capability': capability,
        }
        for key, label, icon, capability in PORTAL_NAV_ITEMS
        if capability in permitted
    ]
    # `get_portal_nav_items` is reached only after Portal authentication in
    # production.  In local shell rendering it is harmless and keeps the
    # settings screen discoverable for manual UI checks.
    key, label, icon = PORTAL_PERSONAL_NAV_ITEM
    items.append({'key': key, 'label': label, 'icon': icon, 'url': reverse('portal_screen', kwargs={'screen': key}), 'capability': ''})
    return items


def portal_screen_allowed(user, screen: str, *, access=None) -> bool:
    return any(item['key'] == screen for item in get_portal_nav_items(user, access=access))
