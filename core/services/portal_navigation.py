"""Server-owned Portal navigation visibility rules."""

from django.urls import reverse


PORTAL_NAV_ITEMS = (
    ('dashboard', 'Dashboard', 'bar-chart-3', ()),
    ('jbl', 'JBL Queue', 'home', ('JBL_OFFICER', 'ADMIN')),
    ('credit', 'Credit', 'shield-check', ('CREDIT_ANALYST', 'ADMIN')),
    ('final', 'Review', 'phone-call', ('ADMIN',)),
    ('requisition', 'Orders', 'shopping-bag', ('HB_STAFF', 'ADMIN')),
    ('deferred', 'Deferred', 'clock', ('JBL_OFFICER', 'CREDIT_ANALYST', 'HB_STAFF', 'ADMIN')),
    ('all', 'All Cases', 'database', ('JBL_OFFICER', 'CREDIT_ANALYST', 'HB_STAFF', 'ADMIN')),
    ('batches', 'Batches', 'layers', ('HB_STAFF', 'ADMIN')),
    ('invoices', 'Invoices', 'receipt-text', ('HB_STAFF', 'ADMIN')),
)

ROLE_ALIASES = {
    'JBL_OFFICER': 'JBL_OFFICER', 'jbl_officer': 'JBL_OFFICER',
    'CREDIT_ANALYST': 'CREDIT_ANALYST', 'credit_analyst': 'CREDIT_ANALYST',
    'ADMIN': 'ADMIN', 'admin': 'ADMIN',
    'HB_STAFF': 'HB_STAFF', 'hb_staff': 'HB_STAFF', 'operations': 'HB_STAFF',
    'head_rural': 'ADMIN',
}


def normalized_portal_roles(staff) -> set[str]:
    """Translate persisted workflow roles to the four shell navigation roles."""
    if staff is None:
        return {'ADMIN'}
    return {
        ROLE_ALIASES.get(str(role).strip(), str(role).strip().upper())
        for role in (staff.roles or [])
    }


def get_portal_nav_items(staff) -> list[dict]:
    roles = normalized_portal_roles(staff)
    return [
        {
            'key': key,
            'label': label,
            'icon': icon,
            'url': reverse('portal_screen', kwargs={'screen': key}),
        }
        for key, label, icon, allowed_roles in PORTAL_NAV_ITEMS
        if not allowed_roles or roles.intersection(allowed_roles)
    ]


def portal_screen_allowed(staff, screen: str) -> bool:
    return any(item['key'] == screen for item in get_portal_nav_items(staff))
