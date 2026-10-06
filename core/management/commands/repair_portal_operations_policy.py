"""Explicit, audited repair of the saved Operations capability matrix."""
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from core.models import WorkflowRoleCapability
from core.services.access_control import apply_capability_matrix_direct
from core.services.workflow_capabilities import default_enabled_capability_keys


class Command(BaseCommand):
    help = 'Preview Operations SysUp/invoice permissions; --apply requires an active Superuser actor.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--actor', type=int, help='Active Django Superuser ID for audit attribution.')

    @transaction.atomic
    def handle(self, *args, **options):
        workflow, role = 'jawabu_portal', 'OPERATIONS_ADMIN'
        rows = list(WorkflowRoleCapability.objects.filter(workflow=workflow, role=role))
        current = ({row.capability_key for row in rows if row.effect == 'allow'} if rows
                   else default_enabled_capability_keys(workflow, role))
        required = {'portal.imports.view', 'portal.imports.commit', 'portal.invoice.write'}
        missing = sorted(required - current)
        self.stdout.write('Operations capabilities to add: ' + (', '.join(missing) or 'none'))
        if not options['apply'] or not missing:
            return
        actor = get_user_model().objects.filter(pk=options['actor'], is_active=True, is_superuser=True).first()
        if not actor:
            raise CommandError('--apply requires --actor identifying an active Django Superuser.')
        change = apply_capability_matrix_direct(requester=actor, workflow=workflow, role=role,
            capability_keys=current | required,
            reason='Enable approved Operations SysUp review/commit and invoice editing; preserve all other saved permissions.')
        self.stdout.write(self.style.SUCCESS(f'Applied audited access-policy request {change.pk}. Staff branch/product/group grants are unchanged.'))
