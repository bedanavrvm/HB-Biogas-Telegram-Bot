from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import ProductVersion, TatTrackerCase
from core.services.tat_bm_stage_rollout import prepare, publish
from core.services.tat_configuration import resolve_tat_configuration, product_config_from_snapshot
from core.services.tat_tracker import (
    apply_side_effects, next_action, previous_stages_complete, stage_by_key,
    stage_tat_minutes, stage_target_minutes_for_case, apply_update,
)


@override_settings(CREDIT_ASSESSMENT_GMAIL_ENABLED=False, TAT_TRACKER_SIGNATURES_ENABLED=False)
class BMAnalysisStageTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser('stage-root', password='local-test')
        self.source = ProductVersion.objects.get(product__code='business', status='published')
        self.old_snapshot = resolve_tat_configuration(self.source, requested_amount=Decimal('25000'))
        self.draft = prepare(self.source.pk, actor=self.actor)
        self.snapshot = resolve_tat_configuration(self.draft, requested_amount=Decimal('25000'))
        self.product = product_config_from_snapshot(self.snapshot)
        start = timezone.now() - timedelta(minutes=60)
        self.case = TatTrackerCase.objects.create(
            group_id='-100synthetic', case_id='SYNTHETIC-BM-1', product_key='business',
            branch='Nakuru', amount=25000, tat_configuration_snapshot=self.snapshot,
            configuration_binding_status=TatTrackerCase.CONFIG_VERSIONED,
            stage_values={'created': (start - timedelta(minutes=10)).isoformat(), 'mpesa_to_admin': start.isoformat()},
            current_stage='bm_analysis_approval',
        )

    def test_prepare_is_idempotent_and_preserves_published_bytes(self):
        self.assertEqual(prepare(self.source.pk, actor=self.actor).pk, self.draft.pk)
        self.source.refresh_from_db()
        self.assertEqual(resolve_tat_configuration(self.source, requested_amount=Decimal('25000')), self.old_snapshot)

    def test_all_paths_have_one_bm_step_between_bro_and_admin(self):
        for amount in (Decimal('25000'), Decimal('100000')):
            snapshot = resolve_tat_configuration(self.draft, requested_amount=amount)
            keys = [item['key'] for item in snapshot['stages']]
            self.assertEqual(keys[:3], ['mpesa_to_admin', 'bm_analysis_approval', 'mpesa_verified'])
            self.assertEqual(keys.count('bm_analysis_approval'), 1)
        self.assertFalse(stage_by_key(self.product, 'bm_analysis_approval').requires_signature_certificate)

    def test_admin_cannot_skip_pending_bm_and_wrong_role_is_denied(self):
        self.assertFalse(previous_stages_complete(self.case, stage_by_key(self.product, 'mpesa_verified')))
        with patch('core.services.tat_tracker.can_user_edit_stage', return_value=False):
            with self.assertRaises(ValueError):
                apply_update(self.case, {'roles': ['BUSINESS_ADMIN']}, {'field': 'bm_analysis_approval', 'value': 'Approved'})

    def test_approved_bm_step_is_timed_and_advances_to_admin(self):
        with patch('core.services.tat_tracker.can_user_edit_stage', return_value=True), patch('core.services.tat_tracker.record_tat_event'):
            apply_update(self.case, {'name': 'Synthetic BM', 'roles': ['BM']},
                         {'field': 'bm_analysis_approval', 'value': 'Approved'})
        self.assertTrue(self.case.stage_values['bm_analysis_approval_ts'])
        self.assertEqual(next_action(self.case).key, 'mpesa_verified')
        bm = stage_by_key(self.product, 'bm_analysis_approval')
        self.assertGreaterEqual(stage_tat_minutes(self.case, bm), Decimal('60'))
        self.assertIsNone(stage_target_minutes_for_case(self.case, {}, self.product, bm))

    def test_decline_terminates_and_stops_clock(self):
        bm = stage_by_key(self.product, 'bm_analysis_approval')
        self.case.stage_values[bm.key] = 'Declined'
        apply_side_effects(self.case, self.product, bm, 'Declined')
        self.assertEqual(self.case.status, 'Declined')
        self.assertIsNone(next_action(self.case))

    def test_old_case_keeps_original_path(self):
        self.case.tat_configuration_snapshot = deepcopy(self.old_snapshot)
        self.assertEqual(next_action(self.case).key, 'mpesa_verified')

    def test_unrelated_draft_blocks_rollout(self):
        from core.services.tat_bm_stage_rollout import inventory
        from core.models import TatConfigurationEvent
        TatConfigurationEvent.objects.filter(action='bm_analysis_stage_prepared').delete()
        self.assertTrue(inventory(['business'])[0]['blockers'])

    def test_inventory_does_not_roll_back_to_expired_published_terms(self):
        from core.services.tat_bm_stage_rollout import inventory
        from core.services.product_catalog import publish_product_version
        expired = deepcopy(self.source)
        expired.pk = None
        expired.version = self.draft.version + 1
        expired.status = ProductVersion.STATUS_DRAFT
        expired.effective_to = min(timezone.localdate(), self.source.effective_from) - timedelta(days=1)
        expired.effective_from = expired.effective_to - timedelta(days=30)
        expired.save()
        config = deepcopy(self.source.tat_configuration)
        config.pk = None
        config.product_version = expired
        config.save()
        expired = publish_product_version(version=expired, actor=self.actor)
        self.assertEqual([row['source_id'] for row in inventory(['business'])], [str(self.source.pk)])
        with self.assertRaisesMessage(ValueError, 'no longer eligible'):
            prepare(expired.pk, actor=self.actor)

    def test_named_projection_with_moved_identity_and_custom_notes(self):
        from core.services.tat_sheet_schema import case_row, stage_names, stage_minute_names, timestamp_names
        from core.services.sheet_columns import NamedColumns
        headers = ['Notes', 'Status', 'Client Name', 'ID NUMBER', 'PHONE NUMBER', 'Branch', 'BRO Name',
                   'Requested Amount', 'Case Created', 'Remarks / Delays', 'TAT Hours', 'TAT Days', 'Case ID']
        for stage in self.product.stages:
            headers.extend([stage_names(stage)[0], stage_minute_names(stage)[0]])
            if stage.auto_timestamp_key:
                headers.append(timestamp_names(stage)[0])
        row = case_row(self.case, self.product, headers, ['keep staff notes'])
        self.assertEqual(row[0], 'keep staff notes')
        self.assertEqual(NamedColumns(headers).value(row, 'Case ID'), self.case.case_id)

    def test_duplicate_index_case_ids_stop_without_writing(self):
        from types import SimpleNamespace
        from core.test_named_sheet import NamedSheet, service_for
        from core.services.tat_tracker import sync_case_index
        headers = ['Case ID', 'Tracker Sheet', 'Row Number', 'Client Name', 'ID NUMBER',
                   'PHONE NUMBER', 'Branch', 'BRO Name', 'Status', 'Created At', 'Last Updated At']
        sheet = NamedSheet(headers, [[self.case.case_id], [self.case.case_id]])
        with patch('core.services.tat_tracker.get_sheets_service', return_value=service_for(sheet)):
            with self.assertRaisesMessage(ValueError, 'Duplicate Case ID'):
                sync_case_index(SimpleNamespace(sheet_id='synthetic'), self.case)
        self.assertFalse(sheet.updates)

    def test_audit_projection_recovers_a_lost_response_without_duplicate_events(self):
        from types import SimpleNamespace
        from core.test_named_sheet import NamedSheet, service_for
        from core.services.tat_tracker import sync_audit_log
        event = self.case.events.create(stage_key='bm_analysis_approval', new_value='Approved', source='miniapp')
        headers = ['Notes', 'Timestamp', 'Actor', 'Tracker Sheet', 'Case ID', 'Row Number',
                   'Stage', 'New Value', 'Old Value', 'Source', 'Event ID']
        sheet = NamedSheet(headers)
        append = sheet.append_rows
        def lost_response(*args, **kwargs):
            append(*args, **kwargs)
            raise RuntimeError('Synthetic lost response')
        with patch('core.services.tat_tracker.get_sheets_service', return_value=service_for(sheet)):
            with patch.object(sheet, 'append_rows', side_effect=lost_response):
                with self.assertRaisesMessage(RuntimeError, 'lost response'):
                    sync_audit_log(SimpleNamespace(sheet_id='synthetic'), self.case)
            event.refresh_from_db()
            self.assertFalse(event.synced_to_sheet)
            sync_audit_log(SimpleNamespace(sheet_id='synthetic'), self.case)
        event.refresh_from_db()
        self.assertTrue(event.synced_to_sheet)
        self.assertEqual(len(sheet.rows), 2)
        self.assertEqual(sheet.rows[1][-1], str(event.pk))

    def test_publish_adds_only_bm_capability_and_bumps_policy(self):
        from core.models import WorkflowRoleCapability, AccessControlPolicyState
        # Exercise repair on an installation where the deployed permission is
        # missing; current clean installations receive it through migration 0204.
        WorkflowRoleCapability.objects.filter(workflow='tat_tracker', role='BM',
                                              capability_key='tat.stage.bm_analysis_approval.update').delete()
        before = set(WorkflowRoleCapability.objects.filter(workflow='tat_tracker', role='BM', effect='allow')
                     .values_list('capability_key', flat=True))
        policy = AccessControlPolicyState.current().version
        published = publish(self.draft, actor=self.actor)
        after = set(WorkflowRoleCapability.objects.filter(workflow='tat_tracker', role='BM', effect='allow')
                    .values_list('capability_key', flat=True))
        self.assertEqual(after - before, {'tat.stage.bm_analysis_approval.update'})
        self.assertGreater(AccessControlPolicyState.current().version, policy)
        self.assertEqual(published.status, 'published')

    def test_role_capability_allows_bm_but_not_admin(self):
        from core.services.tat_tracker import can_user_edit_stage
        publish(self.draft, actor=self.actor)
        stage = stage_by_key(self.product, 'bm_analysis_approval')
        self.assertTrue(can_user_edit_stage({'roles': ['BM']}, self.case, stage))
        self.assertFalse(can_user_edit_stage({'roles': ['BUSINESS_ADMIN']}, self.case, stage))

    def test_builtin_bm_action_survives_an_empty_product_catalogue(self):
        from core.services.workflow_capabilities import capability_definition, capability_definitions
        capability_definitions.cache_clear()
        with patch('core.services.tat_tracker.configured_products', return_value=[]):
            definition = capability_definition('tat_tracker', 'tat.stage.bm_analysis_approval.update')
        self.assertIsNotNone(definition)
        self.assertEqual(set(definition.default_roles), {'BM', 'IT'})

    def test_deployed_bm_permission_needs_no_rollout_command(self):
        from core.models import AccessGrant, GroupSheetConfiguration, UserProfile
        from core.services.access_control import governed_access_grant_mutation
        from core.services.tat_tracker import can_user_edit_stage, staff_user_for_payload
        group = GroupSheetConfiguration.objects.create(
            group_id=self.case.group_id, workflow={'type': 'tat_tracker'},
        )
        actor = get_user_model().objects.create_user('ordinary-tat-bm')
        UserProfile.objects.create(user=actor, telegram_id='989899')
        with governed_access_grant_mutation('Synthetic TAT BM access check'):
            AccessGrant.objects.create(user=actor, workflow='tat_tracker', role='BM',
                                       branch='Nakuru', product='business', group_configuration=group)
        user = staff_user_for_payload(group, {'id': 989899})
        stage = stage_by_key(self.product, 'bm_analysis_approval')
        self.assertTrue(can_user_edit_stage(user, self.case, stage))
        from core.services.tat_tracker import serialize_case_detail
        self.assertTrue(next(row for row in serialize_case_detail(self.case, user)['fields']
                             if row['key'] == stage.key)['editable'])
        # This is an outcome with its own server timestamp, not an Origination
        # signature, even when the independent TAT signature feature is enabled.
        with override_settings(TAT_TRACKER_SIGNATURES_ENABLED=True):
            apply_update(self.case, user, {'field': stage.key, 'value': 'Approved'})
        self.assertTrue(self.case.stage_values['bm_analysis_approval_ts'])
        self.assertFalse(self.case.approval_certificates.exists())

    def test_tat_it_can_update_captured_bm_stage_even_when_product_is_unavailable(self):
        from core.models import AccessGrant, GroupSheetConfiguration, UserProfile
        from core.services.access_control import governed_access_grant_mutation
        from core.services.tat_tracker import can_user_edit_stage, staff_user_for_payload
        from core.services.workflow_capabilities import capability_definitions
        group = GroupSheetConfiguration.objects.create(group_id=self.case.group_id, workflow={'type': 'tat_tracker'})
        actor = get_user_model().objects.create_user('ordinary-tat-it')
        UserProfile.objects.create(user=actor, telegram_id='989900')
        with governed_access_grant_mutation('Synthetic TAT IT access check'):
            AccessGrant.objects.create(user=actor, workflow='tat_tracker', role='IT',
                                       branch='Nakuru', product='business', group_configuration=group)
        capability_definitions.cache_clear()
        with patch('core.services.tat_tracker.configured_products', return_value=[]):
            user = staff_user_for_payload(group, {'id': 989900})
            stage = stage_by_key(self.product, 'bm_analysis_approval')
            self.assertTrue(can_user_edit_stage(user, self.case, stage))

    def tearDown(self):
        from core.services.workflow_capabilities import capability_definitions
        capability_definitions.cache_clear()

    def test_changed_prepared_draft_cannot_be_silently_published(self):
        self.draft.interest_rate += Decimal('1')
        self.draft.save()
        with self.assertRaisesMessage(ValueError, 'prepared product changed'):
            publish(self.draft, actor=self.actor)
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.status, 'draft')

    def test_normal_update_is_revision_checked_idempotent_and_queues_publication(self):
        from types import SimpleNamespace
        from core.services.tat_tracker import update_case
        from core.models import TatUpdateSideEffectDispatch
        publish(self.draft, actor=self.actor)
        group = SimpleNamespace(group_id=self.case.group_id, sheet_id='', workflow={'type': 'tat_tracker'})
        user = {'roles': ['BM'], 'name': 'Synthetic BM'}
        with patch('core.services.tat_tracker.sync_case_to_sheet') as external_write:
            result = update_case(group, user, self.case.case_id,
                                 [{'field': 'bm_analysis_approval', 'value': 'Approved'}],
                                 expected_revision=self.case.workflow_revision, request_id='bm-approve-1')
            self.case.refresh_from_db()
            first_stamp = self.case.stage_values['bm_analysis_approval_ts']
            revision = self.case.workflow_revision
            update_case(group, user, self.case.case_id,
                        [{'field': 'bm_analysis_approval', 'value': 'Approved'}],
                        expected_revision=revision - 1, request_id='bm-approve-1')
            external_write.assert_not_called()
        self.case.refresh_from_db()
        self.assertEqual(self.case.workflow_revision, revision)
        self.assertEqual(self.case.stage_values['bm_analysis_approval_ts'], first_stamp)
        self.assertEqual(self.case.current_stage, 'mpesa_verified')
        self.assertTrue(result)
        self.assertEqual(self.case.events.filter(stage_key='bm_analysis_approval').count(), 1)
        self.assertTrue(TatUpdateSideEffectDispatch.objects.filter(case=self.case).exists())

    def test_target_configuration_is_used_without_inventing_a_default(self):
        stage = stage_by_key(self.product, 'bm_analysis_approval')
        configured = {'tat_targets_minutes': {'business': {'stages': {'bm_analysis_approval': '90'}}}}
        self.assertEqual(stage_target_minutes_for_case(self.case, configured, self.product, stage), Decimal('90'))

    def test_stage_names_cannot_collide_after_normalization(self):
        from django.core.exceptions import ValidationError
        config = self.draft.tat_configuration
        config.stages[1]['sheet_header'] = '  MPESA   Sent to Admin  '
        with self.assertRaises(ValidationError):
            config.full_clean()

    def test_real_bm_grant_remains_branch_scoped(self):
        from core.models import AccessGrant, GroupSheetConfiguration, UserProfile
        from core.services.access_grant_governance import governed_access_grant_mutation
        from core.services.tat_tracker import can_user_edit_stage, staff_user_for_payload
        publish(self.draft, actor=self.actor)
        group = GroupSheetConfiguration.objects.create(group_id=self.case.group_id, display_name='Synthetic BM',
                    workflow={'type': 'tat_tracker', 'branches': ['Nakuru', 'Embu'], 'products': ['business']})
        bm_user = get_user_model().objects.create_user('scoped-synthetic-bm', first_name='Synthetic BM')
        UserProfile.objects.create(user=bm_user, telegram_id='989898')
        with governed_access_grant_mutation('Synthetic BM branch-scope verification'):
            AccessGrant.objects.create(user=bm_user, workflow='tat_tracker', role='BM', branch='Nakuru',
                                       product='business', group_configuration=group)
        user = staff_user_for_payload(group, {'id': 989898})
        stage = stage_by_key(self.product, 'bm_analysis_approval')
        self.assertTrue(can_user_edit_stage(user, self.case, stage))
        self.case.branch = 'Embu'
        self.assertFalse(can_user_edit_stage(user, self.case, stage))

    def test_audit_command_defaults_to_configuration_only(self):
        from io import StringIO
        from django.core.management import call_command
        from core.models import GroupSheetConfiguration
        group = GroupSheetConfiguration.objects.create(group_id='synthetic-audit', display_name='Synthetic audit',
                    workflow={'type': 'tat_tracker'})
        output = StringIO()
        with patch('core.services.sheets.get_sheets_service') as provider:
            call_command('audit_named_sheet_columns', configuration=[str(group.pk)], stdout=output)
        provider.assert_not_called()
        self.assertIn('not_read', output.getvalue())

    def test_unknown_rollout_product_is_not_reported_as_complete(self):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        with self.assertRaises(CommandError):
            call_command('rollout_tat_bm_analysis', product=['synthetic-missing'])


class BMAnalysisDeploymentTests(TestCase):
    def provision(self):
        from importlib import import_module
        from types import SimpleNamespace
        from django.apps import apps
        from django.db import connection
        import_module('core.migrations.0204_tat_bm_analysis_capability').provision_bm_action(
            apps, SimpleNamespace(connection=connection),
        )

    def test_deployment_provisions_only_tat_and_is_idempotent(self):
        from core.models import AccessControlPolicyState, WorkflowRoleCapability, WorkflowRoleCapabilityAuditEvent
        key = 'tat.stage.bm_analysis_approval.update'
        WorkflowRoleCapability.objects.filter(workflow='tat_tracker', capability_key=key).delete()
        other = list(WorkflowRoleCapability.objects.exclude(workflow='tat_tracker').order_by('pk').values())
        version = AccessControlPolicyState.current().version
        audits = WorkflowRoleCapabilityAuditEvent.objects.count()
        self.provision()
        self.assertEqual(set(WorkflowRoleCapability.objects.filter(workflow='tat_tracker',
                         capability_key=key, effect='allow').values_list('role', flat=True)), {'BM', 'IT'})
        self.assertEqual(AccessControlPolicyState.current().version, version + 1)
        self.assertEqual(WorkflowRoleCapabilityAuditEvent.objects.count(), audits + 2)
        self.provision()
        self.assertEqual(AccessControlPolicyState.current().version, version + 1)
        self.assertEqual(WorkflowRoleCapabilityAuditEvent.objects.count(), audits + 2)
        self.assertEqual(list(WorkflowRoleCapability.objects.exclude(workflow='tat_tracker').order_by('pk').values()), other)

    def test_deployment_preserves_explicit_bm_denial(self):
        from core.models import WorkflowRoleCapability
        row = WorkflowRoleCapability.objects.get(workflow='tat_tracker', role='BM',
                    capability_key='tat.stage.bm_analysis_approval.update')
        row.enabled = False
        row.save(update_fields=['enabled'])
        self.provision()
        row.refresh_from_db()
        self.assertEqual(row.effect, 'deny')

    def test_origination_bm_and_it_do_not_grant_tat_access(self):
        from core.models import AccessGrant, GroupSheetConfiguration, UserProfile
        from core.services.access_grant_governance import governed_access_grant_mutation
        from core.services.tat_tracker import staff_user_for_payload
        group = GroupSheetConfiguration.objects.create(group_id='-100-independent-tat', workflow={'type': 'tat_tracker'})
        actor = get_user_model().objects.create_user('origination-only-roles')
        UserProfile.objects.create(user=actor, telegram_id='989901')
        with governed_access_grant_mutation('Synthetic independent Mini App roles'):
            for role in ('BM', 'IT'):
                AccessGrant.objects.create(user=actor, workflow='loan_origination', role=role)
        self.assertFalse(staff_user_for_payload(group, {'id': 989901})['authorized'])
