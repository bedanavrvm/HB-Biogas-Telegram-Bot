"""Automatic unsigned document adoption, with an immutable first-signature boundary."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import timedelta
from threading import Barrier
from unittest import skipUnless
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from core import tests_origination_document_catalogue as fixtures
from origination.models import (
    LoanOriginationApplication, OriginationDocumentTemplate,
    OriginationTemplateConfigurationRevision, OriginationSigningPackage,
    OriginationSigningAction, OriginationSignerSession,
    OriginationOtpChallenge, OriginationSigningActionInvalidation,
)
from origination.services.loan_origination import create_application, OriginationError, OriginationConflict
from origination.services.origination_document_catalogue import catalogue_for_product


class UnsignedDocumentUpdateTests(TestCase):
    _template = fixtures.OriginationDocumentCatalogueTests._template

    def setUp(self):
        fixtures.OriginationDocumentCatalogueTests.setUp(self)
        audit = patch('core.services.compliance_audit.record_event')
        audit.start()
        self.addCleanup(audit.stop)
        self.main = self._template(family='refresh_main', name='Main LAF')
        self.support = self._template(family='refresh_support', name='Support', role='supporting', schema={'fields': []})
        catalogue = catalogue_for_product(self.definition)
        self.app, _ = create_application(product_key=self.definition.product_key, officer=self.officer,
            branch=self.branch.name, client_request_id='refresh-create', primary_template_id=self.main.pk,
            supporting_template_ids=[str(self.support.pk)], expected_catalogue_revision=catalogue['catalogue_revision'])
        self.app.form_payload = {'loan_amount': '25000', 'repayment_tenor_count': 6}
        self.app.save(update_fields=['form_payload'])

    def publish_update(self, source, schema=None):
        OriginationDocumentTemplate.objects.filter(pk=source.pk).update(status='retired')
        return self._template(family=source.document_type, name=source.name, role=source.document_role,
            schema=deepcopy(schema if schema is not None else source.form_schema), version=source.version + 1)

    def refresh(self, **kwargs):
        from origination.services.origination_document_refresh import document_updates, refresh_documents
        plan = document_updates(self.app)
        return refresh_documents(application_id=self.app.pk, actor=self.officer,
            expected_revision=self.app.revision, request_id='refresh-apply', update_token=plan['update_token'], **kwargs)

    def test_refresh_adopts_main_and_support_without_restarting_or_changing_terms(self):
        main = self.publish_update(self.main)
        support = self.publish_update(self.support)
        before = deepcopy(self.app.form_payload), deepcopy(self.app.product_terms_snapshot)
        saved = self.refresh()
        self.assertEqual(saved.pk, self.app.pk)
        self.assertEqual(saved.form_payload, before[0])
        self.assertEqual(saved.product_terms_snapshot['requirements'], before[1]['requirements'])
        self.assertEqual(saved.product_version_id, self.app.product_version_id)
        self.assertEqual(saved.packet_documents.get(document_key='primary').template_id, main.pk)
        self.assertEqual(saved.packet_documents.get(document_key='refresh_support').template_id, support.pk)
        self.assertEqual(saved.revision, self.app.revision + 1)
        self.assertEqual(saved.status, 'draft')
        self.assertEqual(saved.events.filter(action='documents_refreshed').count(), 1)

    def package(self, suffix='one', **kwargs):
        return OriginationSigningPackage.objects.create(application=self.app, application_revision=kwargs.pop('application_revision', self.app.revision),
            external_reference=f'refresh-{suffix}', document_type='refresh_main', context_snapshot={},
            participants_snapshot=[], unsigned_document_hash='a' * 64, **kwargs)

    def session(self, package, **kwargs):
        return OriginationSignerSession.objects.create(package=package, signer_role='borrower',
            token_hash='a' * 64, token_expires_at=timezone.now() + timedelta(hours=1), created_by=self.officer, **kwargs)

    def test_unsigned_reviewed_application_revokes_links_and_reviews_but_keeps_history(self):
        from origination.services.origination_esign import resolve_session
        from hashlib import sha256
        package = self.package(status='in_progress', reviewed_by=self.officer, reviewed_at=timezone.now(),
            frozen_unsigned_document=b'original frozen bytes')
        session = self.session(package, signature_capture={'method': 'typed', 'name': 'Synthetic Applicant'})
        session.token_hash = sha256(b'synthetic-link').hexdigest()
        session.save(update_fields=['token_hash'])
        otp = OriginationOtpChallenge.objects.create(session=session, code_hash='synthetic', binding_sha256='a' * 64,
            send_sequence=1, expires_at=timezone.now() + timedelta(minutes=5))
        self.app.status = 'reviewed'
        self.app.reviewed_by = self.officer
        self.app.reviewed_at = timezone.now()
        self.app.primary_previewed_revision = self.app.revision
        self.app.save()
        self.publish_update(self.main)
        saved = self.refresh()
        self.assertEqual(saved.status, 'draft')
        self.assertIsNone(saved.reviewed_by)
        self.assertIsNone(saved.primary_previewed_revision)
        self.assertFalse(saved.packet_documents.filter(previewed_application_revision__isnull=False).exists())
        package.refresh_from_db(); session.refresh_from_db(); otp.refresh_from_db()
        self.assertEqual(package.status, 'cancelled')
        self.assertEqual(bytes(package.frozen_unsigned_document), b'original frozen bytes')
        self.assertEqual(package.reviewed_by, self.officer)
        self.assertFalse(session.is_active)
        self.assertIsNotNone(otp.invalidated_at)
        with self.assertRaises(OriginationError):
            resolve_session('synthetic-link')
        self.assertEqual(saved.reviewer_notices.count(), 1)

    def test_signed_supporting_document_locks_main_even_after_signature_invalidation(self):
        package = self.package(status='cancelled')
        action = OriginationSigningAction.objects.create(package=package, document_key='refresh_support', slot_key='signature',
            signer_role='guarantor_1', action_type='signature', mode='verified', request_id='signed', actor=self.officer)
        OriginationSigningActionInvalidation.objects.create(action=action, invalidated_by=self.officer,
            reason='Historical withdrawal', request_id='old-withdrawal')
        self.publish_update(self.main)
        with self.assertRaisesMessage(OriginationError, 'already been signed'):
            self.refresh()
        self.app.refresh_from_db()
        self.assertEqual(self.app.packet_documents.get(document_key='primary').template_id, self.main.pk)

    def test_verified_session_and_simulated_signature_also_block_updates(self):
        package = self.package()
        session = self.session(package, verified_at=timezone.now(), status='verified')
        self.publish_update(self.main)
        with self.assertRaisesMessage(OriginationError, 'already been signed'):
            self.refresh()
        session.verified_at = None; session.status = 'pending'; session.save()
        OriginationSigningAction.objects.create(package=package, document_key='primary', slot_key='signature',
            signer_role='officer', action_type='signature', mode='test', request_id='test-signed', actor=self.officer)
        with self.assertRaisesMessage(OriginationError, 'already been signed'):
            self.refresh()

    def test_previewed_typed_signature_is_not_a_signature(self):
        session = self.session(self.package(), signature_capture={'method': 'typed', 'name': 'Synthetic Applicant'},
                               consented_at=timezone.now())
        self.publish_update(self.main)
        self.refresh()
        session.refresh_from_db()
        self.assertFalse(session.is_active)

    def test_completed_without_signatures_can_be_updated(self):
        self.app.status = 'completed'; self.app.save(update_fields=['status'])
        self.publish_update(self.main)
        self.assertEqual(self.refresh().status, 'draft')

    def test_retry_is_bound_to_actor_revision_and_exact_update_plan(self):
        from origination.services.origination_document_refresh import document_updates, refresh_documents
        self.publish_update(self.main)
        plan = document_updates(self.app)
        args = dict(application_id=self.app.pk, expected_revision=self.app.revision,
            request_id='same-refresh', update_token=plan['update_token'])
        saved = refresh_documents(actor=self.officer, **args)
        replay = refresh_documents(actor=self.officer, **args)
        self.assertEqual(saved.revision, replay.revision)
        self.assertEqual(replay.events.filter(action='documents_refreshed').count(), 1)
        other = get_user_model().objects.create_user('refresh-other')
        with self.assertRaises(OriginationError):
            refresh_documents(actor=other, **args)
        with self.assertRaises(OriginationConflict):
            refresh_documents(actor=self.officer, **{**args, 'update_token': 'different'})

    def test_stale_catalogue_confirmation_and_revision_do_not_mutate(self):
        from origination.services.origination_document_refresh import document_updates, refresh_documents
        second = self.publish_update(self.main)
        plan = document_updates(self.app)
        self.publish_update(second)
        args = dict(application_id=self.app.pk, actor=self.officer, expected_revision=self.app.revision,
                    request_id='stale-update', update_token=plan['update_token'])
        with self.assertRaises(OriginationConflict):
            refresh_documents(**args)
        with self.assertRaises(OriginationConflict):
            refresh_documents(**{**args, 'expected_revision': 999})
        self.assertFalse(self.app.events.filter(action='documents_refreshed').exists())

    def test_no_change_does_not_cancel_unsigned_signing_work(self):
        package = self.package()
        saved = self.refresh()
        self.assertEqual(saved.revision, self.app.revision)
        package.refresh_from_db()
        self.assertEqual(package.status, 'pending')

    def test_new_required_fields_do_not_block_refresh_and_local_answers_survive(self):
        from origination.services.origination_document_refresh import document_updates
        doc = self.app.packet_documents.get(document_key='refresh_support')
        doc.field_payload = {'notes': 'Existing local notes'}; doc.save()
        new = deepcopy(self.schema)
        new['sections'].append({'key': 'applicant', 'label': 'Applicant'})
        new['fields'].append({'key': 'new_detail', 'label': 'New detail', 'type': 'text',
                              'section_key': 'applicant', 'required': True})
        self.publish_update(self.main, schema=new)
        self.assertIn('New detail', document_updates(self.app)['new_details'])
        saved = self.refresh()
        self.assertNotIn('new_detail', saved.form_payload)
        self.assertEqual(saved.packet_documents.get(document_key='refresh_support').field_payload['notes'], 'Existing local notes')

    def test_changed_field_meaning_does_not_reinterpret_saved_answers(self):
        self.app.schema_snapshot['fields'].append({'key': 'custom_detail', 'type': 'text'})
        self.app.form_payload['custom_detail'] = 'Old text value'
        self.app.save()
        new = deepcopy(self.schema)
        new['fields'].append({'key': 'custom_detail', 'label': 'Custom detail', 'type': 'date',
                              'section_key': new['sections'][0]['key']})
        self.publish_update(self.main, schema=new)
        saved = self.refresh()
        self.assertNotIn('custom_detail', saved.form_payload)
        event = saved.events.get(action='documents_refreshed')
        self.assertEqual(event.before_values['form_payload']['custom_detail'], 'Old text value')

    def test_failure_rolls_back_snapshots_links_and_revision(self):
        package = self.package(); session = self.session(package)
        self.publish_update(self.main)
        with patch('origination.services.origination_signing_plans.reconcile_document_plan', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):
                self.refresh()
        self.app.refresh_from_db(); session.refresh_from_db(); package.refresh_from_db()
        self.assertEqual(self.app.revision, 1)
        self.assertTrue(session.is_active)
        self.assertEqual(package.status, 'pending')
        self.assertEqual(self.app.packet_documents.get(document_key='primary').template_id, self.main.pk)

    def test_same_reviewer_on_old_packages_does_not_break_refresh(self):
        self.package('old', application_revision=0, status='cancelled', reviewed_by=self.officer, reviewed_at=timezone.now())
        self.package('new', status='in_progress', reviewed_by=self.officer, reviewed_at=timezone.now())
        self.publish_update(self.main)
        self.assertEqual(self.refresh().reviewer_notices.count(), 1)

    def test_api_rechecks_capability_scope_owner_and_method(self):
        from origination.views import portal_origination_document_updates
        self.publish_update(self.main)
        request = RequestFactory().get('/')
        request.origination_user = self.officer
        with patch('origination.views._capability_error', return_value=None), patch('origination.views._application_access_error', return_value=None):
            self.assertEqual(portal_origination_document_updates(request, str(self.app.pk)).status_code, 200)
            request.origination_user = get_user_model().objects.create_user('foreign-refresh-officer')
            self.assertEqual(portal_origination_document_updates(request, str(self.app.pk)).status_code, 403)
        request.origination_user = self.officer
        from django.http import JsonResponse
        with patch('origination.views._capability_error', return_value=JsonResponse({'ok': False}, status=403)):
            self.assertEqual(portal_origination_document_updates(request, str(self.app.pk)).status_code, 403)

    def test_automatic_update_is_repeatable_and_does_not_need_confirmation(self):
        from origination.services.origination_document_refresh import auto_refresh_documents
        newest = self.publish_update(self.main)
        saved = auto_refresh_documents(self.app, actor=self.officer, expected_revision=self.app.revision)
        self.assertEqual(saved.packet_documents.get(document_key='primary').template_id, newest.pk)
        self.assertEqual(saved._document_update_notice['status'], 'updated')
        replay = auto_refresh_documents(saved, actor=self.officer, expected_revision=saved.revision)
        self.assertEqual(saved.revision, replay.revision)
        self.assertEqual(replay.events.filter(action='documents_refreshed').count(), 1)

    def test_automatic_update_skips_signed_applications_without_cancelling_links(self):
        from origination.services.origination_document_refresh import auto_refresh_documents
        package = self.package()
        session = self.session(package, verified_at=timezone.now(), status='verified')
        self.publish_update(self.main)
        saved = auto_refresh_documents(self.app, actor=self.officer)
        self.assertEqual(saved.revision, self.app.revision)
        session.refresh_from_db()
        self.assertTrue(session.is_active)

    def test_automatic_failure_keeps_saved_answers_and_gives_actionable_notice(self):
        from origination.services.origination_document_refresh import auto_refresh_documents
        OriginationDocumentTemplate.objects.filter(pk=self.main.pk).update(status='retired')
        saved = auto_refresh_documents(self.app, actor=self.officer)
        self.assertEqual(saved.form_payload, self.app.form_payload)
        self.assertEqual(saved.revision, self.app.revision)
        self.assertIn('administrator', saved._document_update_notice['message'])

    def test_submission_checks_for_published_updates_before_creating_signing_work(self):
        from origination.views import portal_origination_submit
        self.publish_update(self.main)
        request = RequestFactory().post('/', data={'revision': self.app.revision, 'request_id': 'auto-submit'}, content_type='application/json')
        request.origination_user = self.officer
        with patch('origination.views._capability_error', return_value=None), patch('origination.views._application_access_error', return_value=None):
            response = portal_origination_submit(request, str(self.app.pk))
        import json
        data = json.loads(response.content)
        self.assertEqual(response.status_code, 409)
        self.assertEqual(data['code'], 'documents_updated')
        self.assertEqual(data['application']['status'], 'draft')
        self.assertFalse(self.app.signing_packages.exists())

    def test_automatic_validation_failure_after_snapshot_save_returns_original_state(self):
        from origination.services.origination_document_refresh import auto_refresh_documents
        self.publish_update(self.main)
        with patch('origination.services.origination_signing_plans.reconcile_document_plan', side_effect=OriginationError('Check document roles.')):
            saved = auto_refresh_documents(self.app, actor=self.officer)
        self.assertEqual(saved.revision, self.app.revision)
        self.assertEqual(saved.packet_documents.get(document_key='primary').template_id, self.main.pk)
        self.assertEqual(saved._document_update_notice['status'], 'warning')

    def test_stale_download_token_is_invalid_after_automatic_update(self):
        from origination.services.application_copies import retrieve_copy
        self.publish_update(self.main)
        self.refresh()
        with self.assertRaisesMessage(OriginationConflict, 'Download the latest'):
            retrieve_copy({'application': str(self.app.pk), 'revision': self.app.revision})


@skipUnless(connection.vendor == 'postgresql', 'First-signature concurrency requires PostgreSQL row locks.')
@override_settings(ORIGINATION_TEST_SIGNING_ENABLED=True, SENTRY_ENVIRONMENT='test')
class AutomaticUpdateSigningConcurrencyTests(TransactionTestCase):
    setUp = UnsignedDocumentUpdateTests.setUp
    _template = UnsignedDocumentUpdateTests._template
    package = UnsignedDocumentUpdateTests.package
    publish_update = UnsignedDocumentUpdateTests.publish_update

    def test_first_signature_and_refresh_cannot_both_change_the_bundle(self):
        from origination.services.origination_document_refresh import auto_refresh_documents
        from origination.services.origination_signing import simulate_slot
        package = self.package(test_mode=True)
        package.participants_snapshot = [{'role': 'borrower', 'slots': [{'key': 'signature', 'type': 'signature'}]}]
        package.save(update_fields=['participants_snapshot'])
        newest = self.publish_update(self.main)
        barrier = Barrier(2)

        def execute(operation):
            close_old_connections()
            try:
                actor = get_user_model().objects.get(pk=self.officer.pk)
                barrier.wait(timeout=15)
                if operation == 'sign':
                    try:
                        simulate_slot(package_id=package.pk, actor=actor, document_key='primary',
                            slot_key='signature', signer_role='borrower', expected_revision=self.app.revision,
                            request_id='concurrent-sign', signature_capture={'method': 'typed', 'name': 'Synthetic Applicant'})
                    except OriginationError:
                        pass  # Refresh won and cancelled/revision-invalidated this package.
                else:
                    app = LoanOriginationApplication.objects.get(pk=self.app.pk)
                    auto_refresh_documents(app, actor=actor)
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(execute, ['sign', 'refresh']))
        self.app.refresh_from_db()
        signed = package.actions.filter(action_type='signature').exists()
        self.assertEqual(self.app.packet_documents.get(document_key='primary').template_id,
                         self.main.pk if signed else newest.pk)
        self.assertEqual(self.app.revision, 1 if signed else 2)
