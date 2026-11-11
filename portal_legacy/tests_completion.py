"""Verified imports can close with retained exceptions without blocking new work."""
from copy import deepcopy
import json
import uuid
from unittest.mock import patch

from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse

from core.models import ComplianceAuditEvent, JawabuFarmerMaster
from core.tests_telegram_authentication import BOT_TOKEN
from . import importer, tests_live_cases
from .completion import complete_review, values_digest
from .fence import active, request_blocked
from .models import LegacyDraft, LegacyUpload
from .tests import LegacyHTTPMixin


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN, PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,
                   SECURE_SSL_REDIRECT=False, MINIAPP_TEST_DELETION_ENABLED=True,
                   REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True)
class LegacyReviewCompletionTests(LegacyHTTPMixin, TestCase):
    def prepared(self, **kwargs):
        upload, row = tests_live_cases.LiveImportedCasesTests.partial(self, **kwargs)
        held = LegacyDraft.objects.get(upload_id=upload['id'], legacy__isnull=True)
        body = {'revision': upload['revision'], 'source_sheet': upload['source_sheet'],
            'request_id': str(uuid.uuid4()), 'exceptions': [{'id': str(held.pk),
                'reason': 'Retained for source verification; no new case authorized.',
                'values_sha256': values_digest(held.values)}]}
        return upload, row, held, body

    def complete(self, upload, body, status=200):
        response = self.client.post(reverse('portal_legacy_upload_action', kwargs={
            'upload_id': upload['id'], 'action': 'complete_review'}), json.dumps(body),
            content_type='application/json', HTTP_X_REQUEST_ID=body['request_id'], **self.headers)
        self.assertEqual(response.status_code, status, response.content[:1000])
        return response.json()

    def assert_held(self, upload):
        saved = LegacyUpload.objects.get(pk=upload['id'])
        self.assertTrue(saved.frozen)
        self.assertNotIn('review_completion', saved.state)
        self.assertFalse(ComplianceAuditEvent.objects.filter(action='legacy_review_completed_with_exceptions').exists())

    def test_close_releases_noncase_writes_preserves_cases_source_receipts_and_sheet(self):
        upload, row, held, body = self.prepared()
        request = RequestFactory().post('/api/portal/farmers/new/', '{}', content_type='application/json')
        self.assertTrue(request_blocked(request, {}))
        cases = list(JawabuFarmerMaster.objects.values())
        sources = list(LegacyDraft.objects.order_by('pk').values())
        chunks = list(LegacyUpload.objects.get(pk=upload['id']).chunks.order_by('pk').values())
        source_row = dict(row.values)
        cells = deepcopy(self.book.sheets[0].cells)
        response = self.complete(upload, body)['upload']
        self.assertEqual(response['phase'], 'complete')
        self.assertFalse(response['frozen'])
        self.assertEqual(response['sheet_sync'], {'state': 'complete', 'synced': 1, 'pending': 0,
            'not_imported': 1, 'error': ''})
        self.assertFalse(active(self.group.pk))
        self.assertFalse(request_blocked(request, {}))
        self.assertEqual(list(JawabuFarmerMaster.objects.values()), cases)
        self.assertEqual(list(LegacyDraft.objects.order_by('pk').values()), sources)
        saved = LegacyUpload.objects.get(pk=upload['id'])
        self.assertEqual(list(saved.chunks.order_by('pk').values()), chunks)
        row.refresh_from_db()
        self.assertEqual(row.values, source_row)
        held.refresh_from_db()
        self.assertIsNone(held.legacy_id)
        self.assertEqual(self.book.sheets[0].cells, cells)
        completion = saved.state['review_completion']
        self.assertEqual(completion['source_rows'], {str(held.pk): held.source_row})
        self.assertEqual(completion['retained_exceptions'], 1)
        event = ComplianceAuditEvent.objects.get(action='legacy_review_completed_with_exceptions')
        self.assertEqual(event.actor_id, self.actor.pk)
        self.assertTrue(event.metadata['no_case_or_external_writes'])

    def test_identical_retry_is_one_completion_and_changed_request_is_rejected(self):
        upload, _, _, body = self.prepared()
        first = self.complete(upload, body)['upload']
        second = self.complete(upload, body)['upload']
        self.assertEqual(first['revision'], second['revision'])
        self.assertEqual(first['state']['review_completion'], second['state']['review_completion'])
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='legacy_review_completed_with_exceptions').count(), 1)
        changed = deepcopy(body)
        changed['exceptions'][0]['reason'] = 'Different review facts'
        self.complete(upload, changed, 409)
        changed = {**body, 'request_id': str(uuid.uuid4())}
        self.complete(upload, changed, 409)

    def test_unverified_import_cannot_release_the_hold(self):
        upload, _, _, body = self.prepared(sync=False)
        self.complete(upload, body, 409)
        self.assert_held(upload)

    def test_original_verified_receipt_without_later_revision_tag_can_close(self):
        upload, row, _, body = self.prepared()
        draft = LegacyDraft.objects.get(legacy=row)
        draft.reconciliation['sheet_receipt'].pop('revision')
        draft.save(update_fields=['reconciliation'])
        result = self.complete(upload, body)['upload']
        self.assertEqual(result['phase'], 'complete')
        self.assertFalse(result['frozen'])
        draft.refresh_from_db()
        self.assertNotIn('revision', draft.reconciliation['sheet_receipt'])

    def test_receipt_and_binding_guards_reject_missing_or_wrong_evidence(self):
        upload, row, _, body = self.prepared()
        draft = LegacyDraft.objects.get(legacy=row)
        original = deepcopy(draft.reconciliation)
        for field, value in (('verified', False), ('reference_format', 'uuid'), ('spreadsheet', 'other-book'),
                             ('sheet', 999), ('row', 999), ('digest', ''), ('revision', 999), ('revision', True)):
            with self.subTest(field=field):
                draft.reconciliation = deepcopy(original)
                draft.reconciliation['sheet_receipt'][field] = value
                draft.save(update_fields=['reconciliation'])
                self.complete(upload, body, 409)
                self.assert_held(upload)

    def test_uncertain_write_checkpoints_and_source_conflicts_stay_held(self):
        upload, row, _, body = self.prepared()
        saved = LegacyUpload.objects.get(pk=upload['id'])
        original = deepcopy(saved.state)
        for kind in ('active_plan', 'not_done', 'sync_error', 'publication_not_ready', 'wrong_owner'):
            with self.subTest(kind=kind):
                saved.state = deepcopy(original)
                row.publication_ready = True
                row.farmer.group_configuration = self.group
                if kind == 'active_plan': saved.state['row_sync']['plans'] = [{'pending': True}]
                if kind == 'not_done': saved.state['row_sync']['stage'] = 'rows'
                if kind == 'sync_error': saved.state['sync_error'] = 'Uncertain remote result'
                if kind == 'publication_not_ready': row.publication_ready = False
                if kind == 'wrong_owner': row.farmer.group_configuration = self.other
                row.save(update_fields=['publication_ready'])
                row.farmer.save(update_fields=['group_configuration'])
                saved.save(update_fields=['state'])
                self.complete(upload, body, 409)
                self.assert_held(upload)

    def test_every_exception_needs_current_source_fingerprint_and_a_reason(self):
        upload, row, _, body = self.prepared()
        for kind in ('none', 'duplicate', 'unknown', 'imported', 'changed_source', 'blank_reason'):
            with self.subTest(kind=kind):
                changed = deepcopy(body)
                if kind == 'none': changed['exceptions'] = []
                if kind == 'duplicate': changed['exceptions'] *= 2
                if kind == 'unknown': changed['exceptions'][0]['id'] = '999999999'
                if kind == 'imported': changed['exceptions'][0]['id'] = str(LegacyDraft.objects.get(legacy=row).pk)
                if kind == 'changed_source': changed['exceptions'][0]['values_sha256'] = '0'*64
                if kind == 'blank_reason': changed['exceptions'][0]['reason'] = ' '
                self.complete(upload, changed, 409)
                self.assert_held(upload)

    def test_approved_pending_selection_and_stale_revision_do_not_close(self):
        upload, _, held, body = self.prepared()
        held.approved = True
        held.save(update_fields=['approved'])
        self.complete(upload, body, 409)
        self.assert_held(upload)
        held.approved = False
        held.save(update_fields=['approved'])
        self.complete(upload, {**body, 'revision': body['revision']-1}, 409)
        self.assert_held(upload)

    def test_existing_whole_group_portal_it_authority_is_required(self):
        upload, _, _, body = self.prepared()
        for role, workflow, branch, group in (
            ('JBL_OFFICER', 'jawabu_portal', '', self.group),
            ('IT', 'complaint_cases', '', self.group),
            ('IT', 'jawabu_portal', 'NARROW BRANCH', self.group),
            ('IT', 'jawabu_portal', '', self.other),
        ):
            with self.subTest(role=role, workflow=workflow, branch=branch):
                self.staff(role, workflow=workflow, branch=branch, group=group)
                self.complete(upload, body, 403)
                self.assert_held(upload)
        self.staff('IT')
        self.complete(upload, body)

    def test_signed_identity_is_required(self):
        upload, _, _, body = self.prepared()
        self.headers = {}
        self.complete(upload, body, 403)
        self.assert_held(upload)

    def test_other_register_hold_is_not_released(self):
        upload, _, _, body = self.prepared()
        saved = LegacyUpload.objects.get(pk=upload['id'])
        other = LegacyUpload.objects.create(batch=saved.batch, actor=self.actor, filename='synthetic-eco.xlsx',
            digest='f'*64, source_sheet='Eco-conserve', size=1, phase='backup', frozen=True)
        self.complete(upload, body)
        other.refresh_from_db()
        self.assertTrue(other.frozen)
        self.assertTrue(active(self.group.pk))

    def test_retained_rows_cannot_be_selected_edited_or_committed_after_completion(self):
        upload, _, held, body = self.prepared()
        completed = self.complete(upload, body)['upload']
        self.request('select', {'rows': [{'id': str(held.pk), 'approved': True}]}, upload=completed, status=409)
        self.request('edit', {'id': str(held.pk), 'changes': {'customer_name': 'CHANGED'}}, upload=completed, status=409)
        self.request('commit', upload=completed, status=409)
        with self.assertRaises(ValueError):
            importer.commit_step(LegacyUpload.objects.get(pk=upload['id']), self.actor, None)
        self.assertEqual(JawabuFarmerMaster.objects.count(), 1)

    def test_lease_and_audit_failures_preserve_the_hold(self):
        upload, _, _, body = self.prepared()
        saved = LegacyUpload.objects.select_related('batch__group').get(pk=upload['id'])
        with self.assertRaises(ValueError):
            complete_review(saved, actor=self.actor, access=None, expected_revision=body['revision'],
                request_key=body['request_id'], exceptions=body['exceptions'])
        self.assert_held(upload)
        with patch('core.services.compliance_audit.record_event', side_effect=ValueError('Audit unavailable')):
            self.complete(upload, body, 409)
        self.assert_held(upload)
