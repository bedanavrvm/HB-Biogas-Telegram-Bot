"""Single source of truth for workflow access-grant choices and validation."""

from django.core.exceptions import ValidationError

from core.services.branches import global_branch_choices


WORKFLOW_ROLES = {
    'jawabu_portal': (
        ('JBL_OFFICER', 'JBL Officer'),
        ('CREDIT_ANALYST', 'Credit Analyst'),
        ('HB_STAFF', 'HomeBiogas / Operations Staff'),
        ('ADMIN', 'Portal Administrator'),
    ),
    'complaint_cases': (
        ('OFFICER', 'Complaint Case Officer'),
        ('MANAGER', 'Complaint Case Manager'),
    ),
    'tat_tracker': (
        ('BRO', 'Branch Relationship Officer'),
        ('ADMIN', 'TAT Administrator'),
        ('CA', 'Credit Analyst'),
        ('BM', 'Branch Manager'),
        ('SECRETARY', 'HOCC Secretary'),
        ('CHAIR', 'HOCC Chair'),
        ('LOAN_APPROVER', 'Loan Approver'),
        ('FINANCE', 'Finance'),
        ('IT', 'IT / Override'),
        ('MANAGEMENT', 'Management'),
    ),
}

ROLE_ALIASES = {
    'jawabu_portal': {
        'admin': 'ADMIN', 'jbl_officer': 'JBL_OFFICER',
        'credit_analyst': 'CREDIT_ANALYST', 'operations': 'HB_STAFF',
        'hb_staff': 'HB_STAFF', 'head_rural': 'ADMIN',
    },
}

WORKFLOW_GROUP_TYPES = {
    'jawabu_portal': {'jawabu', 'jawabu_homebiogas'},
    'complaint_cases': {'case'},
    'tat_tracker': {'tat_tracker'},
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
    from core.services.tat_tracker import PRODUCTS
    return [('', 'All products')] + [(key, config.label) for key, config in PRODUCTS.items()]


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
    if workflow != 'tat_tracker' and product:
        errors['product'] = f'{workflow_label(workflow)} does not use product scope.'
    elif workflow == 'tat_tracker':
        from core.services.tat_tracker import PRODUCTS
        if product and product not in PRODUCTS:
            errors['product'] = 'Select a valid TAT Tracker product.'
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
