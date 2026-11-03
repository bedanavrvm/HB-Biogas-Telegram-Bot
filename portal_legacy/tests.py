"""Importer contracts through signed Portal HTTP, real XLSX and real test DB.

Only Google transport and the clock are substituted. Expected facts are literal
worked examples, never calculated with the importer being verified.
"""
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import hashlib
import json
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import AccessGrant, ComplianceAuditChainState, GroupSheetConfiguration, JawabuFarmerMaster, UserProfile, IntegrationOperation
from core.services.access_grant_governance import governed_access_grant_mutation
from core.services.telegram_identity import user_access
from core.tests_telegram_authentication import BOT_TOKEN, signed_init_data
from portal_legacy.models import LegacyUpload, LegacyChunk, LegacyDraft, LegacyRow, LegacyEvent
from portal_legacy.test_support import Book, workbook_bytes, edit_worksheet


class LegacyHTTPMixin:
    def setUp(self):
        super().setUp()
        # Transactional live-server tests flush data-migration singleton rows.
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        self.group = GroupSheetConfiguration.objects.create(group_id='-100legacy-test', sheet_id='synthetic-sheet',
                    display_name='SYNTHETIC OWNER', workflow={'type': 'jawabu_homebiogas'})
        self.other = GroupSheetConfiguration.objects.create(group_id='-100legacy-other', workflow={'type': 'jawabu_homebiogas'})
        self.actor = get_user_model().objects.create_user(username='legacy-superuser', is_superuser=True)
        self.bind(self.actor, 991001)
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        cache = patch('portal_legacy.streaming.gettempdir', return_value=self.directory.name)
        cache.start(); self.addCleanup(cache.stop)
        self.book = Book()
        transport = patch('core.services.sheets.GoogleSheetsService.get_instance', side_effect=self.book.service)
        transport.start(); self.addCleanup(transport.stop)
        self.now = timezone.now()
        clock = patch('portal_legacy.import_views.timezone.now', side_effect=lambda: self.now)
        clock.start(); self.clock = clock; self.addCleanup(clock.stop)

    def bind(self, actor, telegram_id):
        UserProfile.objects.update_or_create(user=actor, defaults={'telegram_id': str(telegram_id)})
        self.headers = {'HTTP_X_TELEGRAM_INIT_DATA': signed_init_data(user={'id': telegram_id})}

    def staff(self, role='IT', *, workflow='jawabu_portal', group=None, branch='', active=True):
        actor = get_user_model().objects.create_user(username='staff-'+uuid.uuid4().hex, is_active=active)
        with governed_access_grant_mutation('Synthetic importer contract fixture'):
            AccessGrant.objects.create(user=actor, workflow=workflow, role=role, group_configuration=group or self.group, branch=branch)
        self.bind(actor, actor.pk+992000)
        return actor

    def request(self, action=None, body=None, *, upload=None, status=200, method='post', query=''):
        if upload:
            path = reverse('portal_legacy_upload_action', kwargs={'upload_id': upload['id'], 'action': action}) if action else reverse('portal_legacy_upload', kwargs={'upload_id': upload['id']})
        else: path = reverse('portal_legacy_uploads')
        headers = {**self.headers, 'HTTP_X_REQUEST_ID': str(uuid.uuid4())}
        if method == 'get': response = self.client.get(path+query, **headers)
        elif action == 'chunk': response = self.client.post(path+query, body, content_type='application/octet-stream', **headers)
        else:
            values = dict(body or {})
            if upload: values.setdefault('revision', upload['revision']); values.setdefault('source_sheet', upload['source_sheet'])
            response = self.client.post(path+query, json.dumps(values), content_type='application/json', **headers)
        self.assertEqual(response.status_code, status, response.content[:800])
        return response.json()

    def create(self, content=None, *, source='Master Data', namespace=None, group=None):
        content = content if content is not None else workbook_bytes()
        result = self.request(body={'group_id': (group or self.group).pk, 'namespace': namespace or uuid.uuid4().hex,
                    'filename': 'synthetic.xlsx', 'digest': hashlib.sha256(content).hexdigest(), 'size': len(content), 'source_sheet': source})
        return result['upload'], content

    def stage(self, content=None, **kwargs):
        upload, content = self.create(content, **kwargs)
        for position, start in enumerate(range(0, len(content), 512*1024)):
            upload = self.request('chunk', content[start:start+512*1024], upload=upload, query=f'?position={position}')['upload']
        upload = self.request('prepare', upload=upload)['upload']
        upload = self.request('stage', upload=upload)['upload']
        return self.finish(upload, 'staging')

    def finish(self, upload, phase):
        for _ in range(1000):
            if upload['phase'] != phase: return upload
            self.now += timedelta(seconds=5)
            upload = self.request('advance', upload=upload)['upload']
        self.fail('Import did not reach a resumable next phase')

    def cleanup(self, upload):
        for _ in range(100):
            result = self.request('cleanup_preview', upload=upload)
            upload = result['upload']
            if result['review']['complete']: break
        else: self.fail('Cleanup preview did not finish')
        upload = self.request('cleanup_confirm', {'token': result['review']['token']}, upload=upload)['upload']
        return self.finish(upload, 'deleting')

    def commit(self, upload):
        upload = self.cleanup(upload)
        upload = self.request('select', {'all': True, 'approved': True}, upload=upload)['upload']
        upload = self.request('commit', upload=upload)['upload']
        return self.finish(upload, 'committing')

    def projection(self, upload):
        upload = self.request('projection_preview', upload=upload)['upload']
        return self.request('projection_confirm', {'manual_edits_paused': True}, upload=upload)['upload']

    def complete(self, upload):
        for _ in range(1000):
            if upload['phase'] == 'complete': return upload
            self.now += timedelta(seconds=5)
            upload = self.request('advance', upload=upload)['upload']
        self.fail('Projection did not complete')

    def rows(self, upload):
        return self.request(upload=upload, method='get')['rows']


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN, PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,
                   SECURE_SSL_REDIRECT=False, MINIAPP_TEST_DELETION_ENABLED=True,
                   REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True)
class LegacyImporterTests(LegacyHTTPMixin, TestCase):
    def test_signed_authentication_is_required(self):
        self.headers = {}
        self.request(method='get', status=403)
        self.assertFalse(LegacyUpload.objects.exists())

    def test_navigation_retains_scoped_it_and_denies_cross_workflow_roles(self):
        from core.services.portal_navigation import get_portal_nav_groups, get_portal_pipeline_stages
        for role, workflow, expected in [('IT', 'jawabu_portal', True), ('OPERATIONS_ADMIN', 'jawabu_portal', False), ('IT', 'loan_origination', False)]:
            with self.subTest(role=role, workflow=workflow):
                actor = self.staff(role, workflow=workflow)
                access = user_access(actor, 'jawabu_portal')
                groups = get_portal_nav_groups(actor, access=access)
                legacy = [g for g in groups if g['label'] == 'Legacy changeover']
                self.assertEqual(bool(legacy), expected)
                if expected: self.assertEqual([i['key'] for i in legacy[0]['items']], ['legacy'])
                stages = get_portal_pipeline_stages(actor, access=access)
                self.assertFalse(any('legacy' in s['screens'].split() for s in stages))

    def test_permission_scope_denials_do_not_create_uploads(self):
        for role, workflow, branch, group in [('OPERATIONS_ADMIN', 'jawabu_portal', '', self.group),
                    ('IT', 'loan_origination', '', self.group), ('IT', 'complaint_cases', '', self.group),
                    ('IT', 'jawabu_portal', '', self.other)]:
            with self.subTest(role=role, workflow=workflow, group=group.pk):
                self.staff(role, workflow=workflow, branch=branch, group=group)
                self.request(body={'group_id': self.group.pk, 'namespace': 'denied', 'size': 1, 'digest': 'a'*64}, status=403)
        self.assertFalse(LegacyUpload.objects.exists())

    def test_it_may_stage_but_cannot_delete_test_data(self):
        self.staff()
        upload = self.stage()
        self.request('cleanup_preview', upload=upload, status=403)
        self.assertFalse(LegacyUpload.objects.get(pk=upload['id']).frozen)

    def test_file_replay_is_idempotent_but_sources_are_separate(self):
        upload, data = self.create(namespace='same-file')
        replay, _ = self.create(data, namespace='another-namespace')
        eco, _ = self.create(data, source='Eco-conserve', namespace='same-file')
        self.assertEqual(replay['id'], upload['id'])
        self.assertNotEqual(eco['id'], upload['id'])
        self.assertEqual(LegacyUpload.objects.count(), 2)

    def test_unsupported_source_and_retarget_are_rejected(self):
        self.request(body={'group_id': self.group.pk, 'namespace': 'bad-source', 'size': 1, 'digest': 'a'*64, 'source_sheet': 'Both'}, status=409)
        upload, _ = self.create()
        self.request('prepare', {'source_sheet': 'Eco-conserve'}, upload=upload, status=409)
        self.assertEqual(LegacyUpload.objects.get(pk=upload['id']).source_sheet, 'Master Data')

    def test_incomplete_and_conflicting_chunk_replays_preserve_source(self):
        upload, data = self.create()
        self.request('prepare', upload=upload, status=409)
        first = self.request('chunk', data, upload=upload, query='?position=0')['upload']
        self.request('chunk', data, upload=first, query='?position=0')
        self.request('chunk', b'X'+data[1:], upload=first, query='?position=0', status=409)
        self.assertEqual(bytes(LegacyChunk.objects.get(upload_id=upload['id']).content), data)

    def test_checksum_mismatch_is_not_staged(self):
        upload, data = self.create()
        self.request('chunk', b'X'+data[1:], upload=upload, query='?position=0')
        self.request('prepare', upload=upload, status=409)
        self.assertFalse(LegacyDraft.objects.exists())

    def test_staging_retains_source_but_creates_no_operational_cases(self):
        upload = self.stage()
        row = self.rows(upload)[0]
        self.assertEqual(row['source_values']['primary_phone'], '712345678')
        self.assertEqual(row['proposal']['fields']['primary_phone'], '254712345678')
        self.assertEqual(row['proposal']['fields']['invoice_amount'], '46000')
        self.assertEqual(upload['total'], 1)
        self.assertFalse(JawabuFarmerMaster.objects.exists())
        self.assertFalse(LegacyEvent.objects.exists())

    def test_repeated_source_row_rolls_back_the_batch(self):
        content = workbook_bytes([[2, 'ONE'], [2, 'TWO']])
        upload, content = self.create(content)
        upload = self.request('chunk', content, upload=upload, query='?position=0')['upload']
        upload = self.request('prepare', upload=upload)['upload']
        upload = self.request('stage', upload=upload)['upload']
        self.request('advance', upload=upload, status=409)
        self.assertFalse(LegacyDraft.objects.exists())
        upload = self.request(upload=upload, method='get')['upload']
        self.assertEqual(upload['phase'], 'staging')

    def test_stale_selection_revision_is_rejected_without_changing_approvals(self):
        upload = self.stage()
        self.request('select', {'revision': upload['revision']-1, 'all': True, 'approved': True}, upload=upload, status=409)
        self.assertEqual(self.request(upload=upload, method='get')['upload']['selected'], 0)

    def test_active_lease_blocks_advance_and_expired_lease_recovers(self):
        upload = self.stage()
        LegacyUpload.objects.filter(pk=upload['id']).update(lease=uuid.uuid4(), lease_until=self.now+timedelta(seconds=30))
        self.request('select', {'all': True, 'approved': True}, upload=upload, status=409)
        self.now += timedelta(seconds=31)
        selected = self.request('select', {'all': True, 'approved': True}, upload=upload)['upload']
        self.assertEqual(selected['selected'], 1)

    def test_invalid_money_blocks_cleanup_without_freezing_or_deleting(self):
        farmer = JawabuFarmerMaster.objects.create(group_configuration=self.group, customer_name='RETAIN ME')
        upload = self.stage(workbook_bytes([[2, 'BAD MONEY', '', '', 5000, 0, 'NaN']]))
        self.assertEqual(self.rows(upload)[0]['proposal']['review_status'], 'blocked')
        self.request('cleanup_preview', upload=upload, status=409)
        self.assertTrue(JawabuFarmerMaster.objects.filter(pk=farmer.pk).exists())
        self.assertFalse(LegacyUpload.objects.get(pk=upload['id']).frozen)

    def test_full_eco_changeover_preserves_master_cases_and_sheet(self):
        master = JawabuFarmerMaster.objects.create(group_configuration=self.group, customer_name='MASTER SENTINEL', legacy_fulfillment_partner='HB')
        old_eco = JawabuFarmerMaster.objects.create(group_configuration=self.group, customer_name='ECO TEST', legacy_fulfillment_partner='ECOCONSERVE')
        before = deepcopy(self.book.sheets[0].cells)
        upload = self.commit(self.stage(source='Eco-conserve'))
        upload = self.complete(self.projection(upload))
        self.assertEqual(upload['committed'], 1)
        self.assertFalse(upload['frozen'])
        self.assertTrue(JawabuFarmerMaster.objects.filter(pk=master.pk, customer_name='MASTER SENTINEL').exists())
        self.assertFalse(JawabuFarmerMaster.objects.filter(pk=old_eco.pk).exists())
        legacy = LegacyRow.objects.get(source_sheet='Eco-conserve')
        self.assertTrue(legacy.publication_ready)
        self.assertEqual(legacy.farmer.legacy_fulfillment_partner, 'ECOCONSERVE')
        self.assertEqual(legacy.farmer.source, 'portal_legacy')
        self.assertEqual(legacy.farmer.invoice_amount, Decimal('46000'))
        self.assertEqual(self.book.sheets[1].row_values(2)[3:7], ['5000', '2500', '7500.00', '46000.00'])
        self.assertEqual(self.book.sheets[0].cells, before)
        self.assertEqual(self.book.replacements, ['Eco-conserve'])
        self.assertFalse(IntegrationOperation.objects.filter(operation_type='miniapp_sheet_delete').exists())
        self.assertTrue(IntegrationOperation.objects.filter(operation_type='miniapp_record_deleted', source_id=str(old_eco.pk)).exists())

    def test_master_changeover_preserves_eco_and_other_owner(self):
        eco = JawabuFarmerMaster.objects.create(group_configuration=self.group, customer_name='ECO SENTINEL', legacy_fulfillment_partner='ECOCONSERVE')
        other = JawabuFarmerMaster.objects.create(group_configuration=self.other, customer_name='OTHER OWNER')
        before = deepcopy(self.book.sheets[1].cells)
        upload = self.complete(self.projection(self.commit(self.stage())))
        self.assertEqual(upload['phase'], 'complete')
        self.assertTrue(JawabuFarmerMaster.objects.filter(pk=eco.pk).exists())
        self.assertTrue(JawabuFarmerMaster.objects.filter(pk=other.pk).exists())
        self.assertEqual(self.book.sheets[1].cells, before)
        self.assertEqual(self.book.replacements, ['Master Data'])

    def test_commit_is_bounded_and_resumes_with_new_client_without_duplicates(self):
        content = workbook_bytes([[i+2, f'SYNTHETIC {i}', '', '', 5000, 0, 46000] for i in range(121)])
        upload = self.cleanup(self.stage(content))
        upload = self.request('select', {'all': True, 'approved': True}, upload=upload)['upload']
        upload = self.request('commit', upload=upload)['upload']
        upload = self.request('advance', upload=upload)['upload']
        self.assertGreater(upload['committed'], 0)
        self.assertLessEqual(upload['committed'], 50)
        self.client = type(self.client)()
        upload = self.request(upload=upload, method='get')['upload']
        upload = self.finish(upload, 'committing')
        self.assertEqual(upload['committed'], 121)
        self.assertEqual(JawabuFarmerMaster.objects.count(), 121)
        self.assertEqual(LegacyEvent.objects.filter(action='imported').count(), 121)
        self.assertEqual(LegacyRow.objects.values('farmer_id').distinct().count(), 121)

    def test_one_identity_collision_is_held_while_other_rows_commit(self):
        content = workbook_bytes([[2, 'FIRST', '', '12345678'], [3, 'SECOND', '', '12345678'], [4, 'THIRD', '', '87654321']])
        upload = self.commit(self.stage(content))
        self.assertEqual(upload['committed'], 2)
        failed = LegacyDraft.objects.get(upload_id=upload['id'], source_row=3)
        self.assertFalse(failed.approved)
        self.assertIn('collision', failed.proposal['commit_error'])
        self.assertFalse(LegacyRow.objects.filter(source_row=3).exists())
        self.request('projection_preview', upload=upload, status=409)
        upload = self.request('select', {'rows': [{'id': failed.pk, 'approved': True, 'note': 'Confirmed separate historical unit'}]}, upload=upload)['upload']
        upload = self.request('commit', upload=upload)['upload']
        upload = self.finish(upload, 'committing')
        self.assertEqual(upload['committed'], 3)
        self.assertEqual(JawabuFarmerMaster.objects.count(), 3)
        self.assertEqual(JawabuFarmerMaster.objects.filter(national_id='12345678').values('customer_id').distinct().count(), 1)

    def test_malformed_phone_and_unknown_decision_are_preserved_without_fabrication(self):
        content = workbook_bytes([[2, 'HISTORICAL', '1234', '', 0, 0, 0, 'Rejected', 'Unclear reason']],
                    headers=['Source Row', 'Customer Name', 'Primary Phone', 'National ID', 'Deposit Paid to HBG',
                             'Deposit Paid to JBL', 'Invoice Amount', 'LEGACY | Outcome | Cleaned', 'LEGACY | Progress Notes | Cleaned'])
        upload = self.commit(self.stage(content))
        legacy = LegacyRow.objects.get(source_row=2)
        self.assertEqual(legacy.values['primary_phone'], '1234')
        self.assertEqual(legacy.farmer.workflow_state, 'legacy_review')
        self.assertFalse(legacy.continuation_confirmed)
        self.assertIsNone(legacy.farmer.credit_decided_at)
        self.assertIsNone(legacy.farmer.final_decided_at)
        self.assertFalse(legacy.publication_ready)
        self.assertEqual(upload['committed'], 1)

    def test_deletion_requires_testing_setting_even_for_superuser(self):
        upload = self.stage()
        with override_settings(MINIAPP_TEST_DELETION_ENABLED=False):
            self.request('cleanup_preview', upload=upload, status=403)
        self.assertFalse(LegacyUpload.objects.get(pk=upload['id']).frozen)

    def test_cleanup_token_is_bound_to_actor_and_register(self):
        upload = self.stage()
        preview = self.request('cleanup_preview', upload=upload)
        upload = preview['upload']
        other_super = get_user_model().objects.create_user(username='other-superuser', is_superuser=True)
        self.bind(other_super, 991002)
        self.request('cleanup_confirm', {'token': preview['review']['token']}, upload=upload, status=409)
        self.bind(self.actor, 991001)
        self.request('cleanup_confirm', {'token': preview['review']['token']+'bad'}, upload=upload, status=409)
        self.assertEqual(LegacyUpload.objects.get(pk=upload['id']).phase, 'ready')

    def test_changed_deletion_impact_blocks_actual_delete(self):
        farmer = JawabuFarmerMaster.objects.create(group_configuration=self.group, customer_name='ORIGINAL')
        upload = self.stage()
        preview = self.request('cleanup_preview', upload=upload)
        upload = self.request('cleanup_confirm', {'token': preview['review']['token']}, upload=preview['upload'])['upload']
        JawabuFarmerMaster.objects.filter(pk=farmer.pk).update(customer_name='CHANGED SINCE REVIEW')
        self.request('advance', upload=upload, status=409)
        self.assertTrue(JawabuFarmerMaster.objects.filter(pk=farmer.pk).exists())
        self.assertTrue(LegacyUpload.objects.get(pk=upload['id']).frozen)

    def test_only_one_cutover_can_hold_an_owner_and_cancel_releases_it(self):
        master = self.stage()
        eco = self.stage(source='Eco-conserve')
        master = self.request('cleanup_preview', upload=master)['upload']
        self.request('cleanup_preview', upload=eco, status=409)
        master = self.request('cancel_preview', upload=master)['upload']
        self.assertFalse(master['frozen'])
        eco = self.request('cleanup_preview', upload=eco)['upload']
        self.assertTrue(eco['frozen'])

    def test_completed_source_cannot_delete_live_import_but_counterpart_can_start(self):
        master = self.complete(self.projection(self.commit(self.stage())))
        new_master = self.stage(workbook_bytes([[2, 'OTHER MASTER']]))
        self.request('cleanup_preview', upload=new_master, status=409)
        eco = self.stage(source='Eco-conserve')
        eco = self.request('cleanup_preview', upload=eco)['upload']
        self.assertTrue(eco['frozen'])
        self.assertEqual(JawabuFarmerMaster.objects.count(), 1)
        self.assertEqual(master['committed'], 1)

    def test_unselected_or_blocked_rows_cannot_enter_commit(self):
        upload = self.cleanup(self.stage())
        upload = self.request('commit', upload=upload)['upload']
        upload = self.finish(upload, 'committing')
        self.assertEqual(upload['committed'], 0)
        self.assertFalse(JawabuFarmerMaster.objects.exists())

    def test_discarded_file_can_be_uploaded_again(self):
        upload, data = self.create()
        self.request('discard', upload=upload)
        replay, _ = self.create(data)
        self.assertEqual(replay['phase'], 'uploading')
        upload = self.request('chunk', data, upload=replay, query='?position=0')['upload']
        self.assertEqual(self.request('prepare', upload=upload)['upload']['phase'], 'mapping')

    def test_missing_selected_tab_and_duplicate_headers_are_not_guessed(self):
        for content in [workbook_bytes(sources=('Eco-conserve',)),
                        workbook_bytes(headers=['Source Row', 'Customer Name', 'Invoice Amount', 'Invoice Amount'])]:
            with self.subTest(digest=hashlib.sha256(content).hexdigest()):
                upload, content = self.create(content)
                upload = self.request('chunk', content, upload=upload, query='?position=0')['upload']
                self.request('prepare', upload=upload, status=409)
        self.assertFalse(LegacyDraft.objects.exists())

    def test_excel_namespaces_blank_rows_and_shared_formula_survive_resume(self):
        content = workbook_bytes([[i+2, f'SYNTHETIC {i}', f'=A{i+2}+1'] for i in range(301)],
                    sources=('Master Data',), headers=['Source Row', 'Customer Name', 'LEGACY | Formula evidence | Cleaned'])
        def excel(data):
            import re
            data = data.replace(b'<worksheet ', b'<worksheet xmlns:x14ac="http://schemas.microsoft.com/office/spreadsheetml/2009/9/ac" ', 1)
            data = data.replace(b'<row r="152">', b'<row r="1510" x14ac:dyDescent="0.25"/><row r="152">')
            data = re.sub(rb'<f>A2\+1</f>', b'<f t="shared" si="0" ref="C2:C302">A2+1</f>', data)
            return re.sub(rb'<f>A(?:[3-9]|[1-9][0-9]|[12][0-9]{2}|30[0-2])\+1</f>', b'<f t="shared" si="0"/>', data)
        content = edit_worksheet(content, excel)
        upload, content = self.create(content)
        upload = self.request('chunk', content, upload=upload, query='?position=0')['upload']
        upload = self.request('prepare', upload=upload)['upload']
        upload = self.request('stage', upload=upload)['upload']
        upload = self.request('advance', upload=upload)['upload']
        self.assertEqual(upload['total'], 250)
        for marker in Path(self.directory.name).rglob('ready'): marker.unlink()
        self.client = type(self.client)()
        upload = self.finish(upload, 'staging')
        self.assertEqual(upload['total'], 301)
        last = LegacyDraft.objects.get(upload_id=upload['id'], source_row=302)
        self.assertEqual(last.values['legacy formula:legacy:Formula evidence'], '=A302+1')
        self.assertEqual(LegacyDraft.objects.get(upload_id=upload['id'], source_row=152).values['customer_name'], 'SYNTHETIC 150')
        self.assertFalse(JawabuFarmerMaster.objects.exists())

    def test_operational_formulas_are_rejected(self):
        content = workbook_bytes([[2, 'FORMULA AMOUNT', '=1+1']], sources=('Master Data',), headers=['Source Row', 'Customer Name', 'Invoice Amount'])
        upload, content = self.create(content)
        upload = self.request('chunk', content, upload=upload, query='?position=0')['upload']
        upload = self.request('prepare', upload=upload)['upload']
        upload = self.request('stage', upload=upload)['upload']
        self.request('advance', upload=upload, status=409)
        self.assertFalse(LegacyDraft.objects.exists())

    def test_projection_requires_every_row_and_unique_case_coverage(self):
        upload = self.commit(self.stage())
        outsider = JawabuFarmerMaster.objects.create(group_configuration=self.group, customer_name='UNACCOUNTED HB')
        self.request('projection_preview', upload=upload, status=409)
        self.assertEqual(self.book.replacements, [])
        self.assertTrue(JawabuFarmerMaster.objects.filter(pk=outsider.pk).exists())

    def test_manual_edits_confirmation_is_required(self):
        upload = self.commit(self.stage())
        upload = self.request('projection_preview', upload=upload)['upload']
        self.request('projection_confirm', {'manual_edits_paused': False}, upload=upload, status=409)
        self.assertEqual(self.book.replacements, [])

    def test_changed_snapshot_is_rejected_and_fresh_review_recovers(self):
        upload = self.projection(self.commit(self.stage()))
        upload = self.finish(upload, 'backup')
        self.book.sheets[0].cells[2] = ['MANUAL EDIT AFTER BACKUP']
        upload = self.finish(upload, 'projecting')
        self.now += timedelta(seconds=5)
        self.request('advance', upload=upload, status=409)
        self.assertEqual(self.book.replacements, [])
        upload = self.request(upload=upload, method='get')['upload']
        upload = self.request('restart_projection', upload=upload)['upload']
        upload = self.complete(self.projection(upload))
        self.assertEqual(upload['phase'], 'complete')
        self.assertEqual(self.book.replacements, ['Master Data'])
        self.assertTrue(LegacyChunk.objects.filter(upload_id=upload['id'], kind__startswith='backup_').exists())

    def test_lost_atomic_replace_ack_resumes_without_second_replacement(self):
        upload = self.projection(self.commit(self.stage()))
        for phase in ('backup', 'projecting', 'verifying'): upload = self.finish(upload, phase)
        self.assertEqual(upload['phase'], 'replacing')
        self.book.lose_ack = True; self.now += timedelta(seconds=5)
        self.request('advance', upload=upload, status=503)
        self.assertEqual(self.book.replacements, ['Master Data'])
        saved = self.request(upload=upload, method='get')['upload']
        self.assertEqual(saved['phase'], 'replacing')
        self.assertTrue(saved['frozen'])
        self.request('restart_projection', upload=saved, status=409)
        finished = self.complete(saved)
        self.assertFalse(finished['frozen'])
        self.assertEqual(self.book.replacements, ['Master Data'])

    def test_readback_corruption_keeps_publication_held(self):
        upload = self.projection(self.commit(self.stage()))
        for phase in ('backup', 'projecting', 'verifying', 'replacing'): upload = self.finish(upload, phase)
        self.book.corrupt_read = 'Master Data'; self.now += timedelta(seconds=5)
        self.request('advance', upload=upload, status=409)
        self.assertFalse(LegacyRow.objects.get().publication_ready)
        saved = self.request(upload=upload, method='get')['upload']
        self.assertTrue(saved['frozen'])
        self.book.corrupt_read = None
        self.assertEqual(self.complete(saved)['phase'], 'complete')

    def test_destination_with_foreign_live_case_id_is_never_replaced(self):
        outsider = JawabuFarmerMaster.objects.create(group_configuration=self.other, customer_name='OTHER OWNER')
        self.book.sheets[0].cells[1].append('Case ID')
        self.book.sheets[0].cells[2] = ['FOREIGN']+['']*8+[str(outsider.pk)]
        upload = self.projection(self.commit(self.stage()))
        self.now += timedelta(seconds=5)
        self.request('advance', upload=upload, status=409)
        self.assertEqual(self.book.replacements, [])

    def test_destinations_cannot_alias_the_same_tab(self):
        upload = self.commit(self.stage())
        self.group.workflow = {'type': 'jawabu_homebiogas', 'eco_conserve_sheet_name': ' master DATA '}
        self.group.save(update_fields=['workflow'])
        self.request('projection_preview', upload=upload, status=409)
        self.assertEqual(self.book.replacements, [])

    def test_row_approvals_and_reconciliation_are_upload_scoped(self):
        master = self.stage()
        eco = self.stage(source='Eco-conserve')
        eco_row = self.rows(eco)[0]
        self.request('select', {'rows': [{'id': eco_row['id'], 'approved': True, 'note': 'Wrong upload'}]}, upload=master)
        self.assertEqual(self.request(upload=eco, method='get')['upload']['selected'], 0)

    def test_wrong_owner_upload_read_and_write_are_denied(self):
        upload, _ = self.create()
        self.staff(group=self.other)
        self.request(upload=upload, method='get', status=403)
        self.request('discard', upload=upload, status=403)
        self.assertEqual(LegacyUpload.objects.get(pk=upload['id']).phase, 'uploading')

    def test_revoked_or_inactive_it_loses_access_to_saved_upload(self):
        actor = self.staff()
        upload = self.stage()
        with governed_access_grant_mutation('Synthetic explicit revocation'):
            AccessGrant.objects.filter(user=actor).update(active=False)
        self.request(upload=upload, method='get', status=403)
        self.assertFalse(JawabuFarmerMaster.objects.exists())

    def test_blank_and_zero_money_and_not_on_sf_have_defined_totals(self):
        content = workbook_bytes([[2, 'ZERO', '', '', '', 0, 0], [3, 'UNKNOWN HB', '', '', 'Not on SF', 2500, 0]])
        upload = self.complete(self.projection(self.commit(self.stage(content))))
        self.assertEqual(upload['committed'], 2)
        self.assertEqual(self.book.sheets[0].row_values(2)[5], '0.00')
        self.assertEqual(self.book.sheets[0].row_values(3)[5], '')
        self.assertEqual(LegacyRow.objects.get(source_row=3).values['deposit_paid_hbg'], 'Not on SF')

    def test_location_and_dates_project_in_agreed_format(self):
        content = workbook_bytes([[2, 'LOCATION', 'nyeri', '24/05/2026']], headers=['Source Row', 'Customer Name', 'County', 'HBG Visit Date'])
        upload = self.complete(self.projection(self.commit(self.stage(content))))
        self.assertEqual(upload['committed'], 1)
        self.assertEqual(self.book.sheets[0].row_values(2)[7:9], ['NYERI', '24-May-2026'])

    def test_negative_or_excess_precision_money_is_blocked(self):
        for value in ['-1', '1.234', 'Infinity', 'not money']:
            with self.subTest(value=value):
                upload = self.stage(workbook_bytes([[2, 'INVALID MONEY', value]], headers=['Source Row', 'Customer Name', 'Invoice Amount']))
                self.assertEqual(self.rows(upload)[0]['proposal']['review_status'], 'blocked')
                self.request('cleanup_preview', upload=upload, status=409)
        self.assertFalse(JawabuFarmerMaster.objects.exists())

    def test_disabled_owner_and_bad_chunk_positions_are_rejected(self):
        self.group.enabled = False; self.group.save(update_fields=['enabled'])
        self.request(body={'group_id': self.group.pk, 'namespace': 'disabled', 'size': 1, 'digest': 'a'*64}, status=404)
        self.group.enabled = True; self.group.save(update_fields=['enabled'])
        upload, data = self.create()
        for position in ['-1', '999', 'abc']:
            self.request('chunk', data, upload=upload, query='?position='+position, status=409)
        self.assertFalse(LegacyChunk.objects.exists())

    def test_projection_capacity_failure_preserves_snapshot_and_owner_hold(self):
        self.book.add_worksheet('UNRELATED LARGE TAB', 100000, 100)
        upload = self.projection(self.commit(self.stage()))
        upload = self.request('advance', upload=upload)['upload']
        self.now += timedelta(seconds=5)
        self.request('advance', upload=upload, status=409)
        self.assertEqual(self.book.replacements, [])
        self.assertTrue(LegacyUpload.objects.get(pk=upload['id']).frozen)
        self.assertTrue(LegacyChunk.objects.filter(upload_id=upload['id'], kind__startswith='backup_').exists())

    def test_cross_register_existing_case_link_cannot_overwrite_identity(self):
        upload = self.cleanup(self.stage())
        eco = JawabuFarmerMaster.objects.create(group_configuration=self.group, customer_name='REAL ECO', legacy_fulfillment_partner='ECOCONSERVE')
        row = self.rows(upload)[0]
        upload = self.request('select', {'rows': [{'id': row['id'], 'approved': True, 'existing_case_id': str(eco.pk), 'note': 'Attempt cross-partner link'}]}, upload=upload)['upload']
        upload = self.request('commit', upload=upload)['upload']
        upload = self.finish(upload, 'committing')
        self.assertEqual(upload['committed'], 0)
        eco.refresh_from_db(); self.assertEqual(eco.customer_name, 'REAL ECO')
        self.assertIn('other register', self.rows(upload)[0]['proposal']['commit_error'])

    def test_publication_is_suppressed_until_selected_register_readback_completes(self):
        from core.services.portal_publication import reserve_farmer_publication
        upload = self.commit(self.stage())
        farmer = LegacyRow.objects.get().farmer
        self.assertEqual(reserve_farmer_publication(farmer, requested_by=self.actor), [])
        self.assertEqual(self.complete(self.projection(upload))['phase'], 'complete')
        self.assertTrue(LegacyRow.objects.get().publication_ready)

    def test_stale_completion_commands_cannot_restart_or_discard_live_import(self):
        upload = self.complete(self.projection(self.commit(self.stage())))
        for command in ['discard', 'cleanup_preview', 'restart_projection', 'projection_preview', 'stage']:
            self.request(command, upload=upload, status=409)
        self.assertEqual(JawabuFarmerMaster.objects.count(), 1)
        self.assertEqual(self.book.replacements, ['Master Data'])

    def test_empty_workbook_cannot_start_an_irrecoverable_cutover(self):
        upload = self.stage(workbook_bytes([]))
        self.assertEqual(upload['total'], 0)
        self.request('cleanup_preview', upload=upload, status=409)
        self.assertFalse(LegacyUpload.objects.get(pk=upload['id']).frozen)

    def test_malformed_workbook_and_excess_columns_have_no_side_effects(self):
        for content in [b'This is not an XLSX', workbook_bytes([[2, 'TOO WIDE']],
                            headers=['Source Row', 'Customer Name']+[f'LEGACY | EXTRA {i} | Cleaned' for i in range(255)])]:
            with self.subTest(size=len(content)):
                upload, content = self.create(content)
                upload = self.request('chunk', content, upload=upload, query='?position=0')['upload']
                self.request('prepare', upload=upload, status=409)
        self.assertFalse(JawabuFarmerMaster.objects.exists())
        self.assertFalse(LegacyDraft.objects.exists())

    def test_source_record_without_source_row_is_not_given_an_invented_identity(self):
        upload, content = self.create(workbook_bytes([['', 'NO SOURCE ROW']]))
        upload = self.request('chunk', content, upload=upload, query='?position=0')['upload']
        upload = self.request('prepare', upload=upload)['upload']
        upload = self.request('stage', upload=upload)['upload']
        self.request('advance', upload=upload, status=409)
        self.assertFalse(LegacyDraft.objects.exists())

    def test_metadata_and_single_row_limits_reject_oversized_xml(self):
        content = workbook_bytes(sources=('Master Data',))
        def oversized(data): return data.replace(b'SYNTHETIC LEGACY', b'X'*(2*1024*1024+1))
        huge_row = edit_worksheet(content, oversized)
        huge_metadata = edit_worksheet(content, lambda data: data+b' '*(8*1024*1024+1), name='xl/workbook.xml')
        for source in [huge_row, huge_metadata]:
            with self.subTest(size=len(source)):
                upload, source = self.create(source)
                for position, start in enumerate(range(0, len(source), 512*1024)):
                    upload = self.request('chunk', source[start:start+512*1024], upload=upload, query=f'?position={position}')['upload']
                self.request('prepare', upload=upload, status=409)
        self.assertFalse(JawabuFarmerMaster.objects.exists())

    def test_legacy_order_and_payment_numbers_are_retired_without_signed_documents(self):
        from requisitions.models import OrderNumberClaim, OrderSequenceState
        from payments.models import PaymentNumberClaim, PaymentSequenceState
        content = workbook_bytes([[2, 'ORDER ONE', 'ECO-88', '#42'], [3, 'ORDER TWO', 'ECO-88', '#42']],
                    headers=['Source Row', 'Customer Name', 'Order Number', 'Payment No'])
        upload = self.commit(self.stage(content, source='Eco-conserve'))
        self.assertEqual(upload['committed'], 2)
        sequence = OrderSequenceState.objects.get(group_configuration=self.group, partner='ECOCONSERVE')
        self.assertEqual(sequence.next_number, 89)
        claim = OrderNumberClaim.objects.get(sequence=sequence, number=88)
        self.assertTrue(claim.retired)
        self.assertIsNone(claim.batch_id)
        payment = PaymentSequenceState.objects.get(group_configuration=self.group)
        self.assertEqual(payment.next_number, 43)
        self.assertEqual(PaymentNumberClaim.objects.filter(sequence=payment, number=42, retired=True).count(), 1)

    def test_branch_it_cannot_borrow_operations_wide_scope(self):
        from core.models import OperationalLocation
        branch = OperationalLocation.objects.create(location_type='branch', code='LEGACY-TEST-BRANCH', name='SYNTHETIC BRANCH')
        actor = self.staff(branch=branch.name)
        with governed_access_grant_mutation('Synthetic independent role scopes'):
            AccessGrant.objects.create(user=actor, workflow='jawabu_portal', role='OPERATIONS_ADMIN', group_configuration=self.group)
        self.request(body={'group_id': self.group.pk, 'namespace': 'no-composed-grants', 'size': 1, 'digest': 'a'*64}, status=403)
        self.assertFalse(LegacyUpload.objects.exists())
