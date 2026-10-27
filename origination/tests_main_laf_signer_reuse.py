"""Synthetic acceptance for document-owned signing and Main LAF reuse."""
import hashlib
import json
from io import BytesIO
from unittest.mock import patch

from django.test import TestCase, RequestFactory, override_settings
from django.urls import reverse
from pypdf import PdfReader

from origination import tests_configuration_isolation as fixtures
from origination.services.loan_origination import create_application, save_application_fields, OriginationError
from origination.services.origination_document_catalogue import catalogue_for_product
from origination.services.origination_documents import packet_signers
from origination.services.origination_signing_plans import freeze_plan


class MainLafSignerReuseTests(TestCase):
    template = fixtures.SelectedPacketTests.template

    def setUp(self):
        fixtures.SelectedPacketTests.setUp(self)
        self.definition.signing_policy = 'all_required'
        self.definition.signer_rules = []
        self.definition.save(update_fields=['signing_policy', 'signer_rules'])

    def signer(self, role='borrower', *, required=True, key=None, identity=True):
        return {'role': role, 'required': required, **({'participant_key': key} if key else {}),
            **({'identity_fields': {'name': 'applicant_name', 'phone': 'applicant_phone'}} if identity and role in {'borrower', 'customer'} else {}),
            'slots': [{'key': 'signature', 'type': 'signature', 'required': required}]}

    def main(self, *signers):
        return self.template('reuse-main', [
            {'key': 'applicant_name', 'type': 'text'}, {'key': 'applicant_phone', 'type': 'phone'}], signers)

    def create(self, main, *supporting):
        catalogue = catalogue_for_product(self.definition)
        return create_application(product_key=self.product.code, officer=self.actor, branch=self.branch.name,
            client_request_id='reuse-create', primary_template_id=main.pk,
            supporting_template_ids=[document.pk for document in supporting],
            expected_catalogue_revision=catalogue['catalogue_revision'])[0]

    def test_borrower_only_document_creates_a_draft_without_forced_staff_signer(self):
        application = self.create(self.main(self.signer()))
        self.assertEqual(application.status, 'draft')
        self.assertEqual([person['role'] for person in freeze_plan(application)], ['borrower'])

    def test_staff_only_document_creates_a_draft_without_forced_borrower(self):
        application = self.create(self.main(self.signer('officer')))
        self.assertEqual(application.status, 'draft')
        self.assertEqual([person['role'] for person in freeze_plan(application)], ['officer'])

    def test_product_defaults_do_not_drop_a_main_borrower_with_a_placement(self):
        self.definition.signing_defaults = [{'participant_key': 'officer'}]
        self.definition.save(update_fields=['signing_defaults'])
        application = self.create(self.main(self.signer(required=False), self.signer('officer')))
        self.assertEqual({person['role'] for person in freeze_plan(application)}, {'borrower', 'officer'})

    def test_legacy_main_borrower_and_support_share_one_participant(self):
        support = self.template('reuse-visit', [], [self.signer(identity=False)], role='supporting')
        application = self.create(self.main(self.signer('customer'), self.signer('officer')), support)
        participants = packet_signers(application)
        borrowers = [person for person in participants if person['role'] in {'borrower', 'customer'}]
        self.assertEqual(len(borrowers), 1)
        self.assertEqual({slot['document_key'] for slot in borrowers[0]['slots']}, {'primary', 'reuse-visit'})
        self.assertEqual(application.signing_participants.filter(role__in=['borrower', 'customer']).count(), 1)

    def save(self, application):
        return save_application_fields(application_id=application.pk, actor=self.actor,
            payload={'applicant_name': 'Synthetic Applicant', 'applicant_phone': '+254700000000',
                     'loan_amount': '5000', 'repayment_tenor': '3'},
            expected_revision=application.revision, request_id='reuse-save')

    def test_main_borrower_identity_wins_over_stale_support_mappings(self):
        support_rule = self.signer()
        support_rule['identity_fields'] = {'name': 'old_name', 'phone': 'old_phone'}
        support = self.template('reuse-visit', [], [support_rule], role='supporting')
        application = self.save(self.create(self.main(self.signer('customer')), support))
        person, = packet_signers(application)
        self.assertEqual(person['identity']['name'], 'Synthetic Applicant')
        self.assertEqual(person['identity']['phone'], '254700000000')
        self.assertTrue(person['dispatch_ready'])
        self.assertEqual(person['slots'][1]['placement_key'], 'borrower.signature')

    def test_multiple_main_borrowers_need_an_explicit_support_binding(self):
        first = self.signer(key='first_borrower')
        second = self.signer(key='second_borrower')
        second['slots'][0]['key'] = 'second_signature'
        main = self.main(first, second)
        support = self.template('reuse-visit', [], [self.signer(identity=False)], role='supporting')
        application = self.create(main, support)
        self.assertEqual(application.status, 'draft')
        with self.assertRaisesMessage(OriginationError, 'Choose which Main LAF borrower'):
            freeze_plan(application)
        document = application.packet_documents.get(template=support)
        document.signer_rules_snapshot[0]['participant_key'] = 'second_borrower'
        document.save(update_fields=['signer_rules_snapshot'])
        people = packet_signers(application)
        self.assertEqual(len(people), 2)
        self.assertEqual([slot['document_key'] for slot in people[1]['slots']], ['primary', 'reuse-visit'])

    def test_other_external_roles_remain_separate_people(self):
        owner = self.signer('asset_owner', key='owner')
        owner['slots'][0]['key'] = 'owner_signature'
        support = self.template('reuse-asset', [], [owner], role='supporting')
        application = self.create(self.main(self.signer()), support)
        self.assertEqual({person['role'] for person in freeze_plan(application)}, {'borrower', 'asset_owner'})

    def test_explicit_borrower_from_another_main_laf_cannot_receive_a_link(self):
        support = self.template('reuse-visit', [], [self.signer(key='other_main_borrower')], role='supporting')
        application = self.create(self.main(self.signer(key='selected_main_borrower')), support)
        with self.assertRaisesMessage(OriginationError, 'Choose which Main LAF borrower'):
            freeze_plan(application)

    def test_legacy_policy_uses_role_binding_for_a_named_main_borrower(self):
        support = self.template('reuse-visit', [], [self.signer(identity=False)], role='supporting')
        application = self.create(self.main(self.signer(key='named_borrower')), support)
        application.signing_policy_snapshot = 'legacy'
        application.save(update_fields=['signing_policy_snapshot'])
        person, = packet_signers(application)
        self.assertEqual(person['role'], 'borrower')
        self.assertEqual(len(person['slots']), 2)

    def test_historical_snapshot_keeps_its_original_participants_and_slot_keys(self):
        support = self.template('reuse-visit', [], [self.signer(identity=False)], role='supporting')
        application = self.create(self.main(self.signer('customer'), self.signer('officer')), support)
        del application.schema_snapshot['signer_binding_version']
        application.save(update_fields=['schema_snapshot'])
        people = packet_signers(application)
        self.assertEqual([person['role'] for person in people], ['customer', 'officer', 'borrower'])
        self.assertTrue(all(slot['key'] == 'signature' and 'placement_key' not in slot
                            for person in people for slot in person['slots']))

    def test_support_editor_does_not_add_duplicate_borrower_fields(self):
        from origination.services.document_editor import save_signers, main_laf_signers
        from origination.services.origination_fields import template_schema_revision
        main = self.main(self.signer(key='joint_borrower'))
        document = self.template('reuse-visit', [], [], role='supporting')
        document.status = 'ready'
        document.save(update_fields=['status'])
        config = document.placement_config
        with patch('origination.services.origination_templates.save_calibration_draft'):
            save_signers(document=document, rules=[self.signer(key='joint_borrower', identity=False)], actor=self.actor,
                schema_revision=template_schema_revision(document), revision=1,
                configuration=config, request_id='support-main-binding')
        document.refresh_from_db()
        self.assertEqual(document.form_schema['fields'], [])
        self.assertNotIn('identity_fields', document.signer_rules[0])
        self.assertEqual(main_laf_signers(document)[0]['key'], 'joint_borrower')

    def test_admin_template_list_shows_version(self):
        document = self.main()
        self.client.force_login(self.actor)
        response = self.client.get(reverse('admin:origination_originationdocumenttemplate_changelist'))
        self.assertContains(response, 'column-version')
        self.assertIn('version', response.context['cl'].list_display)
        self.assertEqual(response.context['cl'].result_list.get().version, document.version)

    def test_create_api_and_retry_return_one_draft_and_one_borrower(self):
        from origination.views import portal_origination_applications
        main = self.main(self.signer())
        catalogue = catalogue_for_product(self.definition)
        body = {'branch': self.branch.name, 'product_key': self.product.code,
                'primary_template_id': str(main.pk), 'catalogue_revision': catalogue['catalogue_revision'],
                'client_request_id': 'reuse-api'}
        request = RequestFactory().post('/api/origination/api/applications/', data=json.dumps(body), content_type='application/json')
        request.origination_user = self.actor
        request.origination_access = None
        with patch('origination.views._capability_error', return_value=None), patch('origination.views._branch_creation_error', return_value=None):
            first = portal_origination_applications(request)
            retry = portal_origination_applications(request)
        self.assertEqual(first.status_code, 201, first.content)
        self.assertEqual(retry.status_code, 200, retry.content)
        self.assertEqual(self.definition.applications.count(), 1)
        self.assertEqual(self.definition.applications.get().signing_participants.count(), 1)

    @override_settings(ORIGINATION_CONDITIONAL_APPROVAL_ENABLED=True, ORIGINATION_ESIGN_ENABLED=True,
        AFRICASTALKING_SMS_ENVIRONMENT='sandbox', AFRICASTALKING_USERNAME='sandbox',
        AFRICASTALKING_API_KEY='synthetic-only', SENTRY_ENVIRONMENT='test', APP_BASE_URL='http://127.0.0.1:8765')
    def test_one_borrower_session_signs_main_and_support_and_preserves_frozen_bytes(self):
        from origination.services.loan_origination import confirm_and_start_conditional_signing
        from origination.services.origination_documents import mark_packet_previewed
        from origination.services.origination_esign import create_signer_session, record_consent_and_signature, issue_otp, verify_otp, complete_staff_signatures
        from origination.services.origination_signing import render_verified_package
        from origination.services.signature_appearance import preview_capture
        def capture(name):
            return {'method': 'typed', 'name': name, 'appearance_version': 2,
                    'preview_sha256': preview_capture(name)['sha256']}
        support = self.template('reuse-visit', [], [self.signer(identity=False)], role='supporting')
        application = self.save(self.create(self.main(self.signer('customer'), self.signer('officer')), support))
        self.assertTrue(mark_packet_previewed(application))
        with patch('origination.services.origination_templates.load_template_source', return_value=self.pdf), patch('origination.services.origination_dispatch.wake_operations'):
            package, _ = confirm_and_start_conditional_signing(application_id=application.pk, actor=self.actor,
                expected_revision=application.revision, request_id='reuse-start')
        original = bytes(package.frozen_unsigned_document)
        original_hash = hashlib.sha256(original).hexdigest()
        participant = next(person for person in package.participants_snapshot if person['role'] == 'customer')
        args = dict(package_id=package.pk, signer_role=participant['role'], participant_id=participant['participant_id'],
                    actor=self.actor, request_id='reuse-link')
        session, token, _ = create_signer_session(**args)
        same, same_token, replayed = create_signer_session(**args)
        self.assertTrue(replayed)
        self.assertEqual((same.pk, same_token), (session.pk, token))
        record_consent_and_signature(raw_token=token, signature_capture=capture('Synthetic Applicant'),
            consent=True, access_mode='self_service', ip_hash='synthetic', reviewed_pages=[1, 2], request_id='reuse-consent')
        _challenge, code, _ = issue_otp(raw_token=token, request_id='reuse-otp', ip_hash='synthetic')
        verify_otp(raw_token=token, code=code, request_id='reuse-verify', ip_hash='synthetic')
        verify_otp(raw_token=token, code=code, request_id='reuse-verify-retry', ip_hash='synthetic')
        self.assertEqual(package.signer_sessions.count(), 1)
        self.assertEqual(package.actions.filter(action_type='signature').count(), 2)
        application.refresh_from_db()
        officer = next(person for person in package.participants_snapshot if person['role'] == 'officer')
        complete_staff_signatures(package_id=package.pk, signer_role='officer', participant_id=officer['participant_id'],
            actor=self.actor, consent=True, signature_capture=capture('Synthetic Officer'),
            expected_revision=application.revision, request_id='reuse-officer-sign')
        self.assertEqual(package.actions.filter(action_type='signature').count(), 3)
        package.refresh_from_db()
        self.assertEqual(hashlib.sha256(bytes(package.frozen_unsigned_document)).hexdigest(), original_hash)
        application.refresh_from_db()
        self.assertEqual(application.status, 'approved')
        signed = PdfReader(BytesIO(render_verified_package(package)))
        self.assertEqual(len(signed.pages), 2)
        self.assertEqual([len(page.get('/Resources').get('/XObject', {})) for page in signed.pages], [2, 1])
