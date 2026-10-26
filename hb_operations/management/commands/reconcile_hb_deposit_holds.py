"""Explicit, narrow repair of legacy deposit-only intake review flags."""
from copy import copy

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from core.models import GroupSheetConfiguration, JawabuFarmerMaster, JawabuPipelineEvent
from core.services.jawabu_case360 import record_pipeline_event
from core.services.jawabu_master import farmup_review_validation_notes
from core.services.jawabu_validation import canonicalize_farmer
from core.services.portal_publication import reserve_farmer_publication


def eligible(farmer):
    if (farmer.status != 'review_needed' or farmer.cleaning_notes.strip() != 'Missing Deposit Paid to HB'
            or farmer.jbl_visit_date or farmer.order_number or farmer.invoice_number
            or farmer.workflow_state not in {'', 'jbl_visit'}
            or farmer.source not in {'jawabu_farmup_review', 'jawabu_farmers_csv'}):
        return False
    # A source explicitly marked Review Needed is independent evidence; the
    # deposit-only cleaning note cannot authorize removing that instruction.
    raw_status = {str(k).strip().lower(): str(v).strip().lower() for k, v in (farmer.raw_data or {}).items()}
    if raw_status.get('status', '') not in {'', 'yes', 'active', 'enabled', 'true'}:
        return False
    cleaned = {key: getattr(farmer, key, '') for key in (
        'national_id', 'primary_phone', 'secondary_phone', 'county', 'sign_date', 'hb_sales_person', 'actual_receipts',
    )}
    if not farmer.customer_name or farmup_review_validation_notes({}, cleaned):
        return False
    candidate = copy(farmer)
    # Older FarmUp rows use uppercase labels. A case-only difference from an
    # active catalogue name is not an independent intake defect; do not write
    # that presentation normalization back as part of this bounded repair.
    from core.services.locations import global_county_choices
    from core.services.branches import global_branch_choices
    for field, choices in [('county', global_county_choices()), ('branch', global_branch_choices())]:
        value = str(getattr(candidate, field) or '').strip().casefold()
        for choice in choices:
            if str(choice).strip().casefold() == value:
                setattr(candidate, field, choice)
                break
    return not canonicalize_farmer(candidate, strict=False)


class Command(BaseCommand):
    help = 'Dry-run by default: reclassify only valid committed FarmUp deposit-only review cases. No external calls.'

    def add_arguments(self, parser):
        parser.add_argument('--configuration', required=True, type=int)
        parser.add_argument('--apply', action='store_true')
        parser.add_argument('--actor', type=int)
        parser.add_argument('--undo-event', help='Reverse one unchanged reconciliation by its audit event UUID; requires --apply.')

    def handle(self, *args, **options):
        if not GroupSheetConfiguration.objects.filter(pk=options['configuration']).exists():
            raise CommandError('Configuration not found.')
        actor = None
        if options['apply']:
            actor = get_user_model().objects.filter(pk=options['actor'], is_active=True, is_superuser=True).first()
            if actor is None:
                raise CommandError('--apply requires --actor with an active Django Superuser ID.')
        if options['undo_event']:
            if not options['apply']:
                raise CommandError('--undo-event requires --apply and an authorized actor.')
            self.undo(options['undo_event'], options['configuration'], actor)
            return
        candidates = JawabuFarmerMaster.objects.filter(
            group_configuration_id=options['configuration'], status='review_needed',
            cleaning_notes='Missing Deposit Paid to HB', jbl_visit_date__isnull=True,
        ).order_by('pk')
        matched = changed = 0
        for case_id in candidates.values_list('pk', flat=True).iterator():
            with transaction.atomic():
                farmer = JawabuFarmerMaster.objects.select_for_update().get(pk=case_id)
                if not eligible(farmer):
                    continue
                matched += 1
                if not options['apply']:
                    continue
                revision = int(farmer.workflow_revision or 1)
                before = {'status': farmer.status, 'cleaning_notes': farmer.cleaning_notes}
                farmer.status, farmer.cleaning_notes, farmer.workflow_revision = 'active', '', revision + 1
                farmer.save(update_fields=['status', 'cleaning_notes', 'workflow_revision', 'updated_at'])
                event = record_pipeline_event(
                    farmer, action='hb_deposit_review_reconciled', stage_key='intake', source='hb_deposit',
                    actor=actor.get_full_name() or actor.get_username(), actor_user=actor,
                    request_id=f'hb-deposit-review:{farmer.pk}:{revision}', old_values=before,
                    new_values={'status': 'active', 'cleaning_notes': ''}, revision_before=revision, revision_after=revision + 1,
                    reason='Legacy missing deposit is a financial hold, not an intake validation failure.',
                )
                reserve_farmer_publication(farmer, request_id=f'hb-deposit-review:{event.pk}', requested_by=actor)
                changed += 1
                self.stdout.write(f'Reconciled case={farmer.pk} event={event.pk}')
        self.stdout.write(f'{"APPLY" if options["apply"] else "DRY RUN"}: eligible={matched}, changed={changed}. No external publication executed.')

    def undo(self, event_id, configuration_id, actor):
        with transaction.atomic():
            try:
                event = JawabuPipelineEvent.objects.get(pk=event_id, action='hb_deposit_review_reconciled', farmer__group_configuration_id=configuration_id)
            except (JawabuPipelineEvent.DoesNotExist, ValidationError, ValueError):
                raise CommandError('Reconciliation event not found in this configuration.') from None
            farmer = JawabuFarmerMaster.objects.select_for_update().get(pk=event.farmer_id)
            key = f'hb-deposit-review-undo:{event.pk}'
            if farmer.pipeline_events.filter(request_id=key).exists():
                self.stdout.write('This reconciliation has already been reversed.')
                return
            if farmer.workflow_revision != event.revision_after or farmer.jbl_visit_date or farmer.status != 'active':
                raise CommandError('Case has changed since reconciliation; automatic reversal is unsafe.')
            revision = farmer.workflow_revision
            farmer.status, farmer.cleaning_notes = event.old_values['status'], event.old_values['cleaning_notes']
            farmer.workflow_revision += 1
            farmer.save(update_fields=['status', 'cleaning_notes', 'workflow_revision', 'updated_at'])
            record_pipeline_event(
                farmer, action='hb_deposit_review_reconcile_reversed', stage_key='intake', source='hb_deposit',
                request_id=key, actor=actor.get_full_name() or actor.get_username(), actor_user=actor,
                old_values=event.new_values, new_values=event.old_values, revision_before=revision, revision_after=revision + 1,
                reason='Explicit operator reversal of unchanged legacy deposit review reconciliation.',
            )
            reserve_farmer_publication(farmer, request_id=key, requested_by=actor)
            self.stdout.write(f'Reversed reconciliation event={event.pk}. No external publication executed.')
