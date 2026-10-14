"""Synthetic contracts for short consent, copies, realistic samples and dates."""
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core import signing
from django.test import SimpleTestCase, TestCase, RequestFactory, override_settings
from django.urls import reverse
from pypdf import PdfReader, PdfWriter

from origination.services.origination_consent import (
    ACKNOWLEDGEMENT_VERSION, acknowledgement_snapshot, valid_acknowledgement,
)
from origination.services.origination_templates import _sample_value_for_field
from origination.services.loan_origination import OriginationError, OriginationConflict, _package_review_scope_hash
from origination import tests_signing_plans


def blank_pdf():
    writer = PdfWriter(); writer.add_blank_page(width=595, height=842)
    output = BytesIO(); writer.write(output)
    return output.getvalue()


class SampleTests(SimpleTestCase):
    def test_realistic_scalar_and_repeating_samples(self):
        fields = [({'type': 'phone'}, '0712345678'), ({'type': 'national_id'}, '99000001'),
                  ({'type': 'text', 'validation': {'format': 'email'}}, 'applicant@example.invalid'),
                  ({'type': 'number', 'validation': {'min': 4, 'max': 6, 'integer': True}}, '4'),
                  ({'type': 'money'}, '12500'),
                  ({'type': 'choice', 'options': [{'code':'old','active':False}, {'code':'ke','label':'Kenya'}]}, 'ke')]
        for field, expected in fields:
            self.assertEqual(_sample_value_for_field(field)[1], expected)
        row = _sample_value_for_field({'type':'repeating_group', 'structure':{'columns':[
            {'key':'phone','type':'phone'}, {'key':'amount','type':'money'}]}})[0][0]
        self.assertEqual(row, {'phone':'0712345678', 'amount':'12500'})

    def test_acknowledgement_binds_the_completion_policy(self):
        app = SimpleNamespace(schema_snapshot={'acknowledgement_version':ACKNOWLEDGEMENT_VERSION},
            signing_policy_snapshot='all_required', approval_roles_snapshot=[])
        package = SimpleNamespace(application=app, consent_policy_id=None, consent_policy_snapshot=acknowledgement_snapshot(app))
        self.assertTrue(valid_acknowledgement(package))
        package.consent_policy_snapshot['signing_policy'] = 'legacy'
        self.assertFalse(valid_acknowledgement(package))


@override_settings(ORIGINATION_CONDITIONAL_APPROVAL_ENABLED=False, ORIGINATION_ESIGN_ENABLED=True,
    AFRICASTALKING_SMS_ENVIRONMENT='sandbox', AFRICASTALKING_USERNAME='sandbox',
    AFRICASTALKING_API_KEY='synthetic-only', SENTRY_ENVIRONMENT='test', APP_BASE_URL='http://127.0.0.1:8765')
class ApplicationPresentationTests(TestCase):
    def setUp(self):
        tests_signing_plans.SigningPlanTests.setUp(self)
        self.application.schema_snapshot = {'fields':[], 'acknowledgement_version':ACKNOWLEDGEMENT_VERSION}
        self.application.save(update_fields=['schema_snapshot'])

    def package(self):
        package = tests_signing_plans.SigningPlanTests.package(self)
        package.consent_policy = None
        package.consent_policy_snapshot = acknowledgement_snapshot(self.application)
        package.review_scope_sha256 = _package_review_scope_hash(package)
        package.save(update_fields=['consent_policy', 'consent_policy_snapshot', 'review_scope_sha256'])
        return package

    def test_new_package_accepts_short_consent_without_policy_activation(self):
        from origination.services.origination_esign import _require_approved_package
        package = self.package()
        _require_approved_package(package)
        package.consent_policy_snapshot['signer_consent_text'] = 'changed'
        with self.assertRaises(OriginationError):
            _require_approved_package(package)

    def test_new_application_captures_acknowledgement_without_active_policy(self):
        from origination.models import OriginationConsentPolicyVersion
        from origination.services.loan_origination import create_application, validate_product_definition
        OriginationConsentPolicyVersion.objects.filter(pk=self.policy.pk).update(status='retired')
        self.definition.form_schema={'fields':[
            {'key':'applicant_name','type':'text','required':True},
            {'key':'applicant_phone','type':'phone','required':True}]}
        self.definition.signer_rules=[
            {'role':'borrower','required':True, 'identity_fields':{'name':'applicant_name','phone':'applicant_phone'},
             'slots':[{'key':'borrower_signature','type':'signature','required':True}]},
            {'role':'officer','required':True,'slots':[{'key':'officer_signature','type':'signature','required':True}]}]
        self.definition.is_active=True
        self.definition.save(update_fields=['form_schema','signer_rules','is_active'])
        validate_product_definition(self.definition)
        with patch('core.services.location_catalog.validate_location_selection', return_value=(None,None,None)):
            application, replayed=create_application(product_key=self.definition.product_key, officer=self.officer,
                branch='Synthetic branch', client_request_id='capture-acknowledgement')
            replay, duplicate=create_application(product_key=self.definition.product_key, officer=self.officer,
                branch='Synthetic branch', client_request_id='capture-acknowledgement')
        self.assertFalse(replayed)
        self.assertTrue(duplicate)
        self.assertEqual(replay.pk,application.pk)
        self.assertEqual(application.schema_snapshot['acknowledgement_version'],ACKNOWLEDGEMENT_VERSION)
        self.assertEqual(application.signing_policy_snapshot,'all_required')

    def test_historical_package_without_policy_is_still_rejected(self):
        from origination.services.origination_esign import _require_approved_package
        package = self.package()
        package.application.schema_snapshot = {'fields':[]}
        with self.assertRaises(OriginationError):
            _require_approved_package(package)

    def test_new_preparation_omits_notice_and_captures_acknowledgement(self):
        from origination.models import OriginationApplicationDocument, OriginationDocumentTemplate
        from origination.services.loan_origination import prepare_review_package
        people = self.application.signer_rules_snapshot
        slots = {p['role']+'.'+s['key']: {'page_number':1, 'box':{'x':20,'y':20+i*45,'width':140,'height':40}}
                 for i,p in enumerate(people) for s in p['slots']}
        self.application.template_configuration_snapshot = {'signature_overlay_manifest':{'slots':slots}}
        self.application.status = 'ready_for_review'
        self.application.save(update_fields=['status','template_configuration_snapshot'])
        template = OriginationDocumentTemplate.objects.create(name='Synthetic LAF', document_type='synthetic', version=1, page_count=1, source_byte_size=1, created_by=self.admin)
        OriginationApplicationDocument.objects.create(application=self.application, template=template, document_key='primary',
            document_role='primary', name='Synthetic LAF', selected=True, signer_rules_snapshot=people,
            schema_snapshot={'fields':[]}, template_snapshot={'configuration':self.application.template_configuration_snapshot})
        with patch('origination.services.origination_documents.render_packet', return_value=(blank_pdf(), [{'key':'primary','page_count':1}])):
            package, replayed = prepare_review_package(application_id=self.application.pk, actor=self.officer,
                expected_revision=self.application.revision, request_id='short-preparation', conditional_approval=True)
        self.assertFalse(replayed)
        self.assertIsNone(package.consent_policy_id)
        self.assertEqual(package.consent_policy_snapshot['delivery'], 'signer_screen')
        self.assertEqual(len(PdfReader(BytesIO(package.frozen_unsigned_document)).pages), 1)

    @patch('origination.services.origination_documents.render_packet', side_effect=lambda app: (blank_pdf(), []))
    def test_unsigned_copy_retries_watermark_and_revision_checks(self, render):
        from origination.services.application_copies import prepare_copy, read_copy_token, retrieve_copy
        token, kind = prepare_copy(application_id=self.application.pk, actor=self.officer,
            revision=self.application.revision, request_id='copy')
        self.assertEqual(kind, 'UNSIGNED')
        content, filename = retrieve_copy(read_copy_token(token))
        self.assertNotIn('UNSIGNED - NOT FINAL', PdfReader(BytesIO(content)).pages[0].extract_text())
        self.assertTrue(filename.endswith('-UNSIGNED.pdf'))
        prepare_copy(application_id=self.application.pk, actor=self.officer, revision=self.application.revision, request_id='copy')
        self.assertEqual(self.application.events.filter(action='application_copy_prepared').count(), 1)
        self.application.revision += 1; self.application.save(update_fields=['revision'])
        with self.assertRaises(OriginationConflict): retrieve_copy(read_copy_token(token))
        with self.assertRaises(signing.BadSignature): read_copy_token(token+'tampered')
        with patch('django.core.signing.time.time', return_value=9999999999):
            with self.assertRaises(signing.SignatureExpired): read_copy_token(token)

    @patch('origination.services.origination_documents.render_packet', side_effect=lambda app: (blank_pdf(), []))
    def test_download_checks_current_actor_access_and_head(self, render):
        from origination.services.application_copies import prepare_copy
        from origination.views import portal_origination_download
        token, _ = prepare_copy(application_id=self.application.pk, actor=self.officer,
            revision=self.application.revision, request_id='download')
        request = RequestFactory().get(reverse('loan_origination_download'), {'token':token})
        self.assertEqual(portal_origination_download(request).status_code, 200)
        head = RequestFactory().head(reverse('loan_origination_download'), {'token':token})
        self.assertEqual(portal_origination_download(head).content, b'')
        self.officer.is_active = False; self.officer.save(update_fields=['is_active'])
        self.assertEqual(portal_origination_download(request).status_code, 403)

    def test_closed_and_incomplete_copies_are_rejected(self):
        from origination.services.application_copies import copy_content
        self.application.status = 'cancelled'
        with self.assertRaises(OriginationError): copy_content(self.application)
        self.application.status = 'draft'
        self.application.schema_snapshot = {'fields':[{'key':'name','type':'text','required':True}]}
        with self.assertRaises(OriginationError): copy_content(self.application)

    def test_approved_copy_preserves_exact_signed_bytes(self):
        from origination.services.application_copies import copy_content
        package = self.package(); package.status='fully_signed'; package.save(update_fields=['status'])
        self.application.status='approved'
        content = blank_pdf()
        with patch('origination.services.origination_esign.signed_package_content', return_value=(package, content)):
            self.assertEqual(copy_content(self.application), (content, 'SIGNED'))

    @patch('origination.services.origination_documents.render_packet', side_effect=lambda app: (blank_pdf(), []))
    def test_scoped_officer_download_is_allowed_but_outside_branch_is_denied(self, render):
        import json
        from django.contrib.auth import get_user_model
        from core.models import AccessGrant, WorkflowRoleCapability
        from core.services.telegram_identity import user_access
        from origination.views import portal_origination_prepare_download, portal_origination_download
        from origination.services.application_copies import prepare_copy
        officer = get_user_model().objects.create_user('synthetic-copy-officer')
        for capability in ('origination.view','origination.create'):
            WorkflowRoleCapability.objects.update_or_create(workflow='loan_origination', role='JBL_OFFICER',
                capability_key=capability, defaults={'effect':'allow'})
        grant = AccessGrant.objects.create(user=officer, workflow='loan_origination', role='JBL_OFFICER', branch=self.application.branch)
        self.application.officer=officer; self.application.save(update_fields=['officer'])
        request = RequestFactory().post('/download/', {'revision':self.application.revision,
            'client_request_id':'scoped-copy'}, content_type='application/json')
        request.origination_user=officer; request.origination_access=user_access(officer, 'loan_origination')
        response=portal_origination_prepare_download(request, str(self.application.pk))
        self.assertEqual(response.status_code, 200, response.content)
        url=json.loads(response.content)['download_url']
        native=RequestFactory().get(url)
        self.assertEqual(portal_origination_download(native).status_code, 200)
        grant.branch='Other branch'; grant.save(update_fields=['branch'])
        self.assertEqual(portal_origination_download(native).status_code, 403)
        with self.assertRaises(OriginationError):
            prepare_copy(application_id=self.application.pk, actor=officer, revision=self.application.revision, request_id='outside-copy')

    def test_download_preparation_requires_telegram_authentication(self):
        with override_settings(ORIGINATION_WEBAPP_REQUIRE_TELEGRAM_AUTH=True):
            response=self.client.post(reverse('loan_origination_prepare_download', args=[self.application.pk]),
                {'revision':self.application.revision,'client_request_id':'unauthorized-copy'}, content_type='application/json')
        self.assertEqual(response.status_code, 403)

    def test_staff_date_uses_one_verified_timestamp_in_nairobi(self):
        from datetime import datetime, timezone as dt_timezone
        from origination.services.origination_esign import complete_staff_signatures, serialize_verified_signing
        package = self.package()
        person = package.participants_snapshot[2]
        person['slots'].append({'document_key':'primary', 'key':'officer_date', 'type':'date_signed', 'required':True})
        package.document_manifest_snapshot[0]['template']['configuration']['signature_overlay_manifest']['slots']['officer.officer_date'] = {
            'page_number':1, 'allowed_area':{'x':20, 'y':170, 'width':140, 'height':20}}
        package.review_scope_sha256 = _package_review_scope_hash(package)
        package.save(update_fields=['participants_snapshot','document_manifest_snapshot','review_scope_sha256'])
        instant = datetime(2026, 10, 13, 21, 1, tzinfo=dt_timezone.utc)
        with patch('django.utils.timezone.now', return_value=instant):
            complete_staff_signatures(package_id=package.pk, signer_role='officer', participant_id=person['participant_id'],
                actor=self.officer, consent=True, signature_capture={'method':'typed','name':'Synthetic Officer'},
                expected_revision=self.application.revision, request_id='staff-date')
        action = package.actions.get(action_type='date_signed')
        self.assertEqual(action.metadata['signed_date'], '2026-10-14')
        self.assertEqual(action.metadata['verified_at'], instant.isoformat())
        projected = next(p for p in serialize_verified_signing(package)['participants'] if p['role']=='officer')
        self.assertEqual(projected['signed_at'], instant.isoformat())
        from origination.services.origination_signing import render_verified_package
        self.assertIn('14/10/2026', PdfReader(BytesIO(render_verified_package(package))).pages[0].extract_text())

    def test_external_date_is_blank_until_otp_verifies_and_retry_keeps_it(self):
        from datetime import datetime, timezone as dt_timezone
        from origination.services.origination_esign import create_signer_session, record_consent_and_signature, issue_otp, verify_otp
        package = self.package()
        person = package.participants_snapshot[0]
        person['slots'].append({'document_key':'primary', 'key':'borrower_date', 'type':'date_signed', 'required':True})
        package.document_manifest_snapshot[0]['template']['configuration']['signature_overlay_manifest']['slots']['borrower.borrower_date'] = {
            'page_number':1,'allowed_area':{'x':20,'y':65,'width':140,'height':20}}
        package.review_scope_sha256 = _package_review_scope_hash(package)
        package.save(update_fields=['participants_snapshot','document_manifest_snapshot','review_scope_sha256'])
        session, token, _ = create_signer_session(package_id=package.pk, signer_role='borrower',
            participant_id=person['participant_id'], actor=self.officer, request_id='borrower-date-session')
        record_consent_and_signature(raw_token=token, signature_capture={'method':'typed','name':'Synthetic Applicant'},
            consent=True, access_mode='self_service', reviewed_pages=[1], ip_hash='synthetic', request_id='borrower-date-capture')
        instant = datetime(2026,10,13,21,1,tzinfo=dt_timezone.utc)
        with patch('django.utils.timezone.now', return_value=instant):
            challenge, code, _ = issue_otp(raw_token=token, request_id='borrower-date-otp', ip_hash='synthetic')
            with self.assertRaises(OriginationError):
                verify_otp(raw_token=token, code='000000' if code!='000000' else '999999', request_id='wrong-date-otp', ip_hash='synthetic')
            self.assertFalse(package.actions.filter(action_type='date_signed').exists())
            verify_otp(raw_token=token, code=code, request_id='borrower-date-verify', ip_hash='synthetic')
        session.refresh_from_db()
        action = package.actions.get(action_type='date_signed')
        self.assertEqual(action.metadata['signed_date'], '2026-10-14')
        self.assertEqual(action.metadata['otp_verified_at'], session.verified_at.isoformat())
        verify_otp(raw_token=token, code=code, request_id='borrower-date-retry', ip_hash='synthetic')
        self.assertEqual(package.actions.filter(action_type='date_signed').count(), 1)
        from origination.services.origination_signing import render_verified_package
        self.assertIn('14/10/2026', PdfReader(BytesIO(render_verified_package(package))).pages[0].extract_text())

    def test_editor_pairs_date_without_duplicate_on_retry(self):
        from origination.models import OriginationDocumentTemplate
        from origination.services.document_editor import save_signers
        from origination.services.origination_fields import template_schema_revision
        document = OriginationDocumentTemplate.objects.create(name='Synthetic editor', document_type='synthetic-editor', version=1, source_byte_size=1,
            page_count=1, created_by=self.admin, form_schema={'fields':[], 'sections':[{'key':'applicant','label':'Applicant'}]})
        rules = [{'role':'officer','label':'Officer','required':True}]
        config = {'field_overlay_manifest':{'fields':{}}, 'signature_overlay_manifest':{'slots':{}}}
        with patch('origination.services.origination_templates.save_calibration_draft'):
            save_signers(document=document, rules=rules, actor=self.admin, schema_revision=0, revision=0,
                configuration=config, request_id='date-slots')
            document.refresh_from_db()
            self.assertEqual([slot['type'] for slot in document.signer_rules[0]['slots']], ['signature','date_signed'])
            save_signers(document=document, rules=document.signer_rules, actor=self.admin,
                schema_revision=template_schema_revision(document), revision=0, configuration=config, request_id='date-slots-again')
            document.refresh_from_db()
            self.assertEqual(len(document.signer_rules[0]['slots']), 2)
            # Two placements for one person reuse an existing date where possible
            # and gain a distinct companion for the additional signature.
            rules=document.signer_rules
            rules[0]['slots'].append({'key':'another_signature','type':'signature','required':True})
            save_signers(document=document, rules=rules, actor=self.admin,
                schema_revision=template_schema_revision(document), revision=0, configuration=config, request_id='another-date')
            document.refresh_from_db()
            dates=[slot for slot in document.signer_rules[0]['slots'] if slot['type']=='date_signed']
            self.assertEqual({slot['signature_key'] for slot in dates}, {'signature','another_signature'})

    def test_status_groups_filter_before_paging_and_preserve_raw_status(self):
        import json
        from origination.models import LoanOriginationApplication
        from origination.views import portal_origination_applications
        from core.services.telegram_identity import user_access
        from origination.services.origination_queues import STATUS_GROUPS
        for status, _label in LoanOriginationApplication.STATUS_CHOICES:
            LoanOriginationApplication.objects.create(reference_number='ORG-GROUP-'+status,
                product_definition=self.definition, officer=self.officer, branch='Synthetic branch',
                status=status, schema_snapshot={'fields':[]}, signing_policy_snapshot='legacy')
        def read(parameters, actor=None):
            actor = actor or self.officer
            request = RequestFactory().get('/applications/', parameters)
            request.origination_user = actor
            request.origination_access = user_access(actor, 'loan_origination')
            return portal_origination_applications(request)
        for group, (_label, statuses) in STATUS_GROUPS.items():
            response = read({'status_group':group,'queue':'applications','page_size':10})
            self.assertEqual(response.status_code, 200, response.content)
            data = json.loads(response.content)
            self.assertTrue(all(item['status'] in statuses for item in data['applications']))
            self.assertEqual(len(data['status_group_options']), 5)
        self.assertEqual(read({'status_group':'invented'}).status_code, 400)
        data = json.loads(read({'status':'approved'}).content)
        self.assertEqual({item['status'] for item in data['applications']}, {'approved'})
        self.assertEqual(read({}, self.outsider).status_code, 403)
