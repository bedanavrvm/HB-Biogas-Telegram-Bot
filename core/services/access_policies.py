"""Single source of truth for workflow access-grant choices and validation."""

from django.core.exceptions import ValidationError

from core.services.branches import global_branch_choices


# ``is_superuser`` is a Django technical-administration flag.  It must never
# be used as a Mini App business role or as a shortcut around AccessGrant.
BUSINESS_ADMIN_ROLE = 'BUSINESS_ADMIN'
OPERATIONS_ADMIN_ROLE = 'OPERATIONS_ADMIN'
LEGACY_BUSINESS_ADMIN_ROLE = 'ADMIN'
BUSINESS_ADMIN_WORKFLOWS = frozenset({
    'jawabu_portal',
    'tat_tracker',
    'spin_credit_analysis',
})


WORKFLOW_ROLES = {
    'jawabu_portal': (
        ('JBL_OFFICER', 'JBL Officer'),
        ('BM', 'Branch Manager'),
        ('MANAGEMENT', 'Management'),
        ('CREDIT_ANALYST', 'Credit Analyst'),
        ('HB_STAFF', 'HomeBiogas / Operations Staff'),
        (OPERATIONS_ADMIN_ROLE, 'Operations Administrator'),
        ('IT', 'IT / Platform Support'),
        # The stable code is retained so existing grants and audit evidence do
        # not need a semantic rewrite.  Portal staff see the actual business
        # authority: Head of Rural.
        (BUSINESS_ADMIN_ROLE, 'Head of Rural'),
    ),
    'complaint_cases': (
        ('OFFICER', 'Complaint Case Officer'),
        ('MANAGER', 'Complaint Case Manager'),
        ('HB_STAFF', 'HomeBiogas Resolution Staff'),
        ('IT', 'IT / Platform Support'),
    ),
    'tat_tracker': (
        ('BRO', 'Branch Relationship Officer'),
        (BUSINESS_ADMIN_ROLE, 'Business Administrator'),
        ('CA', 'Credit Analyst'),
        ('BM', 'Branch Manager'),
        ('SECRETARY', 'HOCC Secretary'),
        ('CHAIR', 'HOCC Chair'),
        ('LOAN_APPROVER', 'Loan Approver'),
        ('FINANCE', 'Finance'),
        ('IT', 'IT / Override'),
        ('MANAGEMENT', 'Management'),
    ),
    'spin_credit_analysis': (
        ('CREDIT_ANALYST', 'Credit Analyst'),
        ('IT', 'IT / Platform Support'),
        (BUSINESS_ADMIN_ROLE, 'Business Administrator'),
    ),
}

ROLE_ALIASES = {
    'jawabu_portal': {
        'admin': BUSINESS_ADMIN_ROLE, 'business_admin': BUSINESS_ADMIN_ROLE,
        'jbl_officer': 'JBL_OFFICER',
        'credit_analyst': 'CREDIT_ANALYST', 'operations': 'HB_STAFF',
        'hb_staff': 'HB_STAFF', 'head_rural': BUSINESS_ADMIN_ROLE,
        'operations_admin': OPERATIONS_ADMIN_ROLE, 'ops_admin': OPERATIONS_ADMIN_ROLE,
        'branch_manager': 'BM', 'bm': 'BM', 'management': 'MANAGEMENT',
    },
    'tat_tracker': {
        'admin': BUSINESS_ADMIN_ROLE,
        'business_admin': BUSINESS_ADMIN_ROLE,
    },
    'spin_credit_analysis': {
        'analyst': 'CREDIT_ANALYST',
        'credit_analyst': 'CREDIT_ANALYST',
        'admin': BUSINESS_ADMIN_ROLE,
        'business_admin': BUSINESS_ADMIN_ROLE,
    },
}

WORKFLOW_GROUP_TYPES = {
    'jawabu_portal': {'jawabu', 'jawabu_homebiogas'},
    'complaint_cases': {'case'},
    'tat_tracker': {'tat_tracker'},
    'spin_credit_analysis': {'spin_credit_analysis'},
}


def canonical_access_role(workflow: str, role: str) -> str:
    value = str(role or '').strip()
    aliases = ROLE_ALIASES.get(workflow, {})
    return aliases.get(value.casefold(), value.upper())


def role_choices():
    labels = {}
    workflows = {}
    for workflow, roles in WORKFLOW_ROLES.items():
        for role, label in roles:
            labels.setdefault(role, label)
            workflows.setdefault(role, []).append(workflow_label(workflow))
    return [
        (role, f'{labels[role]} — {" / ".join(workflows[role])}')
        for role in labels
    ]


def workflow_label(workflow: str) -> str:
    return {
        'jawabu_portal': 'Jawabu Portal',
        'complaint_cases': 'Complaint Cases',
        'tat_tracker': 'TAT Tracker',
        'spin_credit_analysis': 'SPIN / Credit Analysis',
    }.get(workflow, workflow)


def role_workflow_map():
    """Return the workflows where each canonical role may be assigned."""
    return {
        role: {
            workflow
            for workflow, roles in WORKFLOW_ROLES.items()
            if role in {value for value, _label in roles}
        }
        for role in {value for roles in WORKFLOW_ROLES.values() for value, _label in roles}
    }


def branch_choices():
    return [('', 'All branches')] + [(value, value) for value in global_branch_choices()]


def product_choices():
    from core.models import Product
    return [('', 'All products')] + [
        (product.code, product.name)
        for product in Product.objects.filter(active=True).order_by('sort_order', 'name')
    ]


def validate_access_scope(*, workflow, role, branch='', product='', group_configuration=None):
    errors = {}
    canonical_role = canonical_access_role(workflow, role)
    allowed_roles = {value for value, _ in WORKFLOW_ROLES.get(workflow, ())}
    if canonical_role not in allowed_roles:
        errors['role'] = f'Select a role valid for {workflow_label(workflow)}.'
    if workflow == 'complaint_cases' and branch:
        errors['branch'] = 'Complaint Cases access is group-scoped; leave branch as All branches.'
    elif branch and branch not in global_branch_choices():
        errors['branch'] = 'Select a configured branch.'
    if workflow == 'complaint_cases' and product:
        errors['product'] = 'Complaint Cases access is group-scoped; leave product as All products.'
    elif product:
        valid_products = {key for key, _label in product_choices() if key}
        if product not in valid_products:
            errors['product'] = 'Select a valid global product.'
    if group_configuration is not None:
        group_type = str((group_configuration.workflow or {}).get('type') or '')
        if group_type not in WORKFLOW_GROUP_TYPES.get(workflow, set()):
            errors['group_configuration'] = (
                f'This group is configured for {group_type or "an unspecified workflow"}, '
                f'not {workflow_label(workflow)}.'
            )
    if errors:
        raise ValidationError(errors)
    return canonical_role
