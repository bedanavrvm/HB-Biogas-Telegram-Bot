"""Synthetic document copies: selection, immutable signed pages and authorization."""
from datetime import datetime, timezone as dt_timezone
import hashlib
from io import BytesIO
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core import signing
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from pypdf import PdfReader
from reportlab.pdfgen.canvas import Canvas

from core.models import AccessGrant, ComplianceAuditChainState, WorkflowRoleCapability
from core.services.telegram_identity import user_access
from origination.models import (
    LoanOriginationApplication, OriginationApplicationDocument, OriginationDocumentTemplate,
    OriginationProductDefinition, OriginationSigningPackage,
)
from origination.services.application_copies import (
    IncompleteCopyConfirmation, copy_content, copy_filename, download_choices,
    prepare_copy, read_copy_token, retrieve_copy,
)
from origination.services.loan_origination import OriginationConflict, OriginationError, serialize_application
from origination.views import portal_origination_download, portal_origination_prepare_download


def labelled_pdf(*labels):
    stream = BytesIO()
    canvas = Canvas(stream, pagesize=(595, 842))
    for label in labels:
        canvas.drawString(40, 750, label)
        canvas.showPage()
    canvas.save()
    return stream.getvalue()


class ApplicationDownloadTests(TestCase):
    def setUp(self):
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        self.actor = get_user_model().objects.create_superuser('synthetic-download-editor', '', 'test-only')
        self.definition = OriginationProductDefinition.objects.create(product_key='synthetic-download', name='Training Loan')
        self.app = LoanOriginationApplication.objects.create(reference_number='ORG-DOWNLOAD-TEST',
            product_definition=self.definition, officer=self.actor, branch='Training', schema_snapshot={'fields': []},
            form_payload={'applicant_full_name': 'Synthetic Applicant', 'loan_amount': '100000'})
        self.sources = {'primary': labelled_pdf('Main page 1', 'Main page 2'),
                        'guarantee': labelled_pdf('Guarantee page'), 'home_visit': labelled_pdf('Home visit page')}
        for index, key in enumerate(self.sources):
            fields = [{'key': 'guarantee_notes', 'type': 'text'}] if key == 'guarantee' else []
            config = {'document_type': key, 'field_overlay_manifest': {'fields': {}},
                      'signature_overlay_manifest': {'slots': {}}}
            for field in fields:
                config['field_overlay_manifest']['fields'][field['key']] = {
                    'context_key': field['key'], 'page_number': 1,
                    'box': {'x': 10, 'y': 10, 'width': 100, 'height': 18},
                }
            template = OriginationDocumentTemplate.objects.create(document_type=key, version=1,
                document_key=key, document_role='primary' if key == 'primary' else 'supporting',
                name=key.title(), status='active', page_count=2 if key == 'primary' else 1,
                source_byte_size=len(self.sources[key]), source_sha256=hashlib.sha256(self.sources[key]).hexdigest(),
                drive_file_id='synthetic-' + key, created_by=self.actor)
            OriginationApplicationDocument.objects.create(application=self.app, template=template,
                document_key=key, document_role=template.document_role, display_order=index,
                name='Main LAF' if key == 'primary' else 'Guarantee' if key == 'guarantee' else 'Home visit',
                inclusion_mode='optional', selected=True, template_snapshot={'configuration': config},
                schema_snapshot={'fields': fields})
        self.enterContext(patch('origination.services.origination_templates.load_template_source',
            side_effect=lambda template: self.sources[template.document_key]))

    def prepare(self, key='', request_id='copy', **extra):
        return prepare_copy(application_id=self.app.pk, actor=self.actor, revision=self.app.revision,
            request_id=request_id, document_key=key, **extra)

    def approve(self, *, notice=False):
        labels = ['Signed main 1', 'Signed main 2', 'Signed guarantee', 'Signed home visit']
        manifest = [{'key': 'primary', 'name': 'Frozen Main LAF', 'page_count': 2},
                    {'key': 'guarantee', 'name': 'Frozen Guarantee', 'page_count': 1},
                    {'key': 'home_visit', 'name': 'Frozen Home visit', 'page_count': 1}]
        if notice:
            labels.insert(0, 'Historical consent notice')
            manifest.insert(0, {'key': 'conditional_approval_notice', 'page_count': 1})
        content = labelled_pdf(*labels)
        self.app.status = 'approved'
        self.app.save(update_fields=['status'])
        return OriginationSigningPackage.objects.create(application=self.app, application_revision=self.app.revision,
            external_reference='SYNTHETIC-DOWNLOAD', document_type='primary', context_snapshot={}, participants_snapshot=[],
            document_manifest_snapshot=manifest, status='fully_signed', pending_signed_document=content,
            signed_document_hash=hashlib.sha256(content).hexdigest()), content

    def test_unsigned_combined_and_each_document_use_actual_renderer_and_order(self):
        expected = {'': ['Main page 1', 'Main page 2', 'Guarantee page', 'Home visit page'],
                    'primary': ['Main page 1', 'Main page 2'], 'guarantee': ['Guarantee page'], 'home_visit': ['Home visit page']}
        for key, labels in expected.items():
            with self.subTest(key=key):
                token, kind = self.prepare(key, request_id='render-' + key)
                content, filename = retrieve_copy(read_copy_token(token))
                self.assertEqual(kind, 'UNSIGNED')
                self.assertEqual([page.extract_text().strip() for page in PdfReader(BytesIO(content)).pages], labels)
                if key:
                    self.assertIn('Main LAF' if key == 'primary' else key.replace('_', ' ').capitalize(), filename)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, 'draft')
        self.assertEqual(self.app.revision, 1)
        self.assertIsNone(self.app.primary_previewed_revision)
        self.assertFalse(self.app.events.filter(action__in=['document_previewed', 'document_packet_previewed']).exists())
        self.assertFalse(self.app.signing_packages.exists())

    def test_selected_documents_only_and_bad_selectors(self):
        self.app.packet_documents.filter(document_key='home_visit').update(selected=False)
        self.assertEqual([item['document_key'] for item in download_choices(self.app)], ['', 'primary', 'guarantee'])
        for key in ['home_visit', 'unknown', '../primary', [], True, 1, 'x' * 81, 'conditional_approval_notice']:
            with self.subTest(key=key), self.assertRaises(OriginationError):
                self.prepare(key)
        self.assertFalse(self.app.events.filter(action='application_copy_prepared').exists())

    def test_main_laf_is_first_even_when_supporting_display_order_is_lower(self):
        self.app.packet_documents.filter(document_key='primary').update(display_order=99)
        self.app.packet_documents.filter(document_key='home_visit').update(display_order=0)
        self.app.packet_documents.filter(document_key='guarantee').update(display_order=0)
        content, _kind = copy_content(self.app)
        self.assertEqual([page.extract_text().strip() for page in PdfReader(BytesIO(content)).pages],
            ['Main page 1', 'Main page 2', 'Guarantee page', 'Home visit page'])

    def test_incomplete_bundle_warning_does_not_generate_a_pdf(self):
        from origination.views import portal_origination_packet_preview
        self.app.packet_documents.filter(document_key='guarantee').update(
            schema_snapshot={'fields': [{'key': 'guarantee_notes', 'type': 'text', 'required': True}]})
        request = RequestFactory().post('/', {'revision': self.app.revision}, content_type='application/json')
        request.origination_user = self.actor
        request.origination_access = user_access(self.actor, 'loan_origination')
        with patch('origination.views.render_packet') as renderer:
            response = portal_origination_packet_preview(request, str(self.app.pk))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(json.loads(response.content)['code'], 'incomplete_preview_confirmation_required')
        renderer.assert_not_called()

    def test_completed_unsigned_application_keeps_combined_and_individual_downloads(self):
        self.app.status = 'completed'
        self.app.save(update_fields=['status'])
        for key in ['', 'primary', 'guarantee', 'home_visit']:
            token, kind = self.prepare(key, request_id='completed-' + key)
            content, _filename = retrieve_copy(read_copy_token(token))
            self.assertEqual(kind, 'UNSIGNED')
            self.assertGreater(len(PdfReader(BytesIO(content)).pages), 0)
        self.app.refresh_from_db()
        self.assertEqual(self.app.status, 'completed')
        self.assertFalse(self.app.signing_packages.exists())

    def test_individual_validation_does_not_require_other_documents(self):
        from origination.tests_form_projection import layout
        self.app.packet_documents.filter(document_key='home_visit').update(
            schema_snapshot={'fields': [{'key': 'contact_phone', 'type': 'phone', 'required': True}]},
            template_snapshot={'configuration': layout('contact_phone')},
            field_payload={'contact_phone': 'bad-phone'})
        with self.assertRaises(OriginationError):
            self.prepare()
        self.prepare('primary')
        self.prepare('guarantee', request_id='valid-guarantee')
        with self.assertRaises(OriginationError):
            self.prepare('home_visit', allow_incomplete=True)

    def test_bundle_preview_uses_real_renderer_for_missing_supporting_fields(self):
        from origination.views import portal_origination_packet_preview
        self.app.packet_documents.filter(document_key='guarantee').update(
            schema_snapshot={'fields': [{'key': 'guarantee_notes', 'type': 'text', 'required': True}]})
        request = RequestFactory().post('/', {'revision': self.app.revision, 'allow_incomplete': True,
            'client_request_id': 'actual-rendered-bundle'}, content_type='application/json')
        request.origination_user = self.actor
        request.origination_access = user_access(self.actor, 'loan_origination')
        response = portal_origination_packet_preview(request, str(self.app.pk))
        self.assertEqual(response.status_code, 200, response.content[:150])
        self.assertEqual(response['X-Preview-Complete'], 'false')
        self.assertEqual(response['X-Document-Count'], '3')
        pages = PdfReader(BytesIO(response.content)).pages
        self.assertEqual([page.extract_text().strip() for page in pages],
            ['Main page 1', 'Main page 2', 'Guarantee page', 'Home visit page'])
        self.app.refresh_from_db()
        self.assertIsNone(self.app.primary_previewed_revision)
        self.assertFalse(self.app.packet_documents.filter(completed_at__isnull=False).exists())

    def test_incomplete_preview_confirmation_never_grants_access(self):
        from origination.views import portal_origination_packet_preview
        actor = get_user_model().objects.create_user('synthetic-unauthorized-preview')
        request = RequestFactory().post('/', {'revision': self.app.revision, 'allow_incomplete': True}, content_type='application/json')
        request.origination_user = actor
        request.origination_access = user_access(actor, 'loan_origination')
        self.assertEqual(portal_origination_packet_preview(request, str(self.app.pk)).status_code, 403)

    def test_bundle_warning_code_survives_authenticated_message_contract(self):
        self.app.packet_documents.filter(document_key='guarantee').update(
            schema_snapshot={'fields': [{'key': 'guarantee_notes', 'type': 'text', 'required': True}]})
        with override_settings(ORIGINATION_WEBAPP_REQUIRE_TELEGRAM_AUTH=False):
            self.client.force_login(self.actor)
            response = self.client.post(reverse('loan_origination_packet_preview', args=[self.app.pk]),
                {'revision': self.app.revision, 'client_request_id': 'authenticated-warning'},
                content_type='application/json', HTTP_X_MINIAPP_MESSAGE_CONTRACT='2')
        self.assertEqual(response.status_code, 400, response.content)
        self.assertEqual(response.json()['code'], 'incomplete_preview_confirmation_required')
        from core.services.miniapp_messages import normalize_miniapp_response
        normalized = normalize_miniapp_response(RequestFactory().post('/', HTTP_X_MINIAPP_MESSAGE_CONTRACT='2'),
            response, workflow='loan_origination')
        payload = json.loads(normalized.content)
        self.assertEqual(payload['code'], 'incomplete_preview_confirmation_required')
        self.assertIn('missing', payload['message'])

    def test_supporting_copy_does_not_require_unrelated_main_input(self):
        from origination.tests_form_projection import layout
        self.app.schema_snapshot = {'fields': [{'key': 'applicant_phone', 'type': 'phone', 'required': True}]}
        self.app.form_payload['applicant_phone'] = 'bad-phone'
        self.app.template_configuration_snapshot = layout('applicant_phone')
        self.app.save(update_fields=['schema_snapshot', 'form_payload', 'template_configuration_snapshot'])
        self.prepare('guarantee')
        with self.assertRaises(OriginationError):
            self.prepare('primary')

    def test_shared_value_documents_keep_individual_validation_scoped(self):
        from origination.tests_value_contracts import field, schema
        from origination.tests_form_projection import layout
        self.app.schema_snapshot = schema(field('applicant_full_name'))
        self.app.template_configuration_snapshot = layout('applicant_full_name')
        self.app.save(update_fields=['schema_snapshot', 'template_configuration_snapshot'])
        for document in self.app.packet_documents.all():
            document.schema_snapshot = (self.app.schema_snapshot if document.document_key == 'primary'
                else schema(field('contact_phone', type='phone', scope='document')) if document.document_key == 'home_visit'
                else schema())
            document.field_payload = {'contact_phone': 'bad-phone'} if document.document_key == 'home_visit' else {}
            document.template_snapshot = {'configuration': layout(*(field['key'] for field in document.schema_snapshot['fields']))}
            document.save(update_fields=['schema_snapshot', 'field_payload', 'template_snapshot'])
        self.prepare('primary')
        self.prepare('guarantee', request_id='shared-guarantee')
        with self.assertRaises(OriginationError):
            self.prepare('home_visit', allow_incomplete=True)

    def test_incomplete_confirmation_is_specific_and_keeps_selection(self):
        from origination.tests_form_projection import layout
        self.app.packet_documents.filter(document_key='guarantee').update(
            template_snapshot={'configuration': layout('name')},
            schema_snapshot={'fields': [{'key': 'name', 'type': 'text', 'required': True}]})
        with self.assertRaises(IncompleteCopyConfirmation):
            self.prepare('guarantee')
        self.assertFalse(self.app.events.filter(action='application_copy_prepared').exists())
        token, _ = self.prepare('guarantee', allow_incomplete=True)
        self.assertEqual(read_copy_token(token)['document_key'], 'guarantee')
        self.assertEqual(len(PdfReader(BytesIO(retrieve_copy(read_copy_token(token))[0])).pages), 1)

    def test_request_replay_and_selection_are_bound(self):
        first, _ = self.prepare('primary')
        replay, _ = self.prepare('primary')
        self.assertEqual(read_copy_token(first), read_copy_token(replay))
        self.assertEqual(self.app.events.filter(action='application_copy_prepared').count(), 1)
        with self.assertRaises(OriginationConflict):
            self.prepare('guarantee')
        with self.assertRaises(OriginationConflict):
            self.prepare('')

    def test_approved_combined_preserves_exact_bytes_and_individuals_preserve_signed_pages(self):
        package, original = self.approve(notice=True)
        source = PdfReader(BytesIO(original))
        with patch('origination.services.origination_documents.render_document', side_effect=AssertionError('No re-render')):
            self.assertEqual(copy_content(self.app), (original, 'SIGNED'))
            for key, pages in {'primary': [1, 2], 'guarantee': [3], 'home_visit': [4]}.items():
                with self.subTest(key=key):
                    token, kind = self.prepare(key, request_id='signed-' + key)
                    payload = read_copy_token(token)
                    self.assertEqual(payload['document_source']['package_id'], str(package.pk))
                    self.assertEqual(kind, 'SIGNED')
                    output = PdfReader(BytesIO(retrieve_copy(payload)[0]))
                    self.assertEqual([page.get_contents().get_data() for page in output.pages],
                                     [source.pages[index].get_contents().get_data() for index in pages])
        self.assertNotIn('conditional_approval_notice', [item['document_key'] for item in download_choices(self.app)])

    def test_approved_uses_frozen_manifest_not_current_rows(self):
        self.approve()
        self.app.packet_documents.filter(document_key='guarantee').update(name='Changed draft name', selected=False)
        choices = download_choices(self.app)
        self.assertEqual(choices[2]['label'], 'Frozen Guarantee')
        self.assertTrue(choices[2]['available'])
        self.prepare('guarantee')

    def test_bad_historical_boundaries_do_not_break_combined_copy(self):
        package, content = self.approve()
        for manifest in [[], {}, [{'key': 'primary', 'page_count': True}],
                [{'key': 'primary', 'page_count': 2}, {'key': 'primary', 'page_count': 2}],
                [{'key': 'primary', 'page_count': 100}], [{'key': 'support', 'page_count': 4}]]:
            with self.subTest(manifest=manifest):
                package.document_manifest_snapshot = manifest
                package.save(update_fields=['document_manifest_snapshot'])
                self.assertEqual(copy_content(self.app)[0], content)
                with self.assertRaises(OriginationError):
                    copy_content(self.app, document_key='primary')
        package.document_manifest_snapshot = []
        package.save(update_fields=['document_manifest_snapshot'])
        self.assertFalse(download_choices(self.app)[1]['available'])

    def test_changed_signed_source_or_manifest_invalidates_individual_link(self):
        package, _ = self.approve()
        token, _ = self.prepare('guarantee')
        package.document_manifest_snapshot[1]['name'] = 'Different document'
        package.save(update_fields=['document_manifest_snapshot'])
        with self.assertRaises(OriginationConflict):
            retrieve_copy(read_copy_token(token))
        package.pending_signed_document = labelled_pdf('Tampered')
        package.save(update_fields=['pending_signed_document'])
        with self.assertRaises(OriginationError):
            copy_content(self.app, document_key='primary')

    def test_archival_does_not_invalidate_an_individual_copy(self):
        package, content = self.approve()
        token, _ = self.prepare('guarantee')
        package.archive_status = 'uploaded'
        package.final_drive_file_id = 'synthetic-signed-archive'
        package.pending_signed_document = b''
        package.save(update_fields=['archive_status', 'final_drive_file_id', 'pending_signed_document'])
        with patch('core.services.order_approval.GoogleDriveMediaStorage') as storage:
            storage.return_value.download.return_value = content
            copied, _ = retrieve_copy(read_copy_token(token))
            self.assertEqual(PdfReader(BytesIO(copied)).pages[0].extract_text().strip(), 'Signed guarantee')
            storage.return_value.download.assert_called_once_with('synthetic-signed-archive')

    def test_legacy_combined_tokens_and_receipts_stay_compatible(self):
        token, _ = self.prepare()
        payload = read_copy_token(token)
        payload.pop('document_key')
        self.app.events.filter(request_id='copy').update(after_values=payload)
        replay, _ = self.prepare()
        self.assertEqual(read_copy_token(replay), payload)
        self.assertEqual(retrieve_copy(payload)[1], payload['filename'])

    def test_individual_tokens_reject_revision_selection_and_expiry_changes(self):
        token, _ = self.prepare('primary')
        payload = read_copy_token(token)
        changed = {**payload, 'document_key': 'guarantee'}
        with self.assertRaises(OriginationConflict):
            retrieve_copy(changed)
        with self.assertRaises(signing.BadSignature):
            read_copy_token(token + 'tampered')
        with patch('django.core.signing.time.time', return_value=9999999999), self.assertRaises(signing.SignatureExpired):
            read_copy_token(token)
        self.app.revision += 1
        self.app.save(update_fields=['revision'])
        with self.assertRaises(OriginationConflict):
            retrieve_copy(payload)

    def test_individual_filename_is_distinct_and_sanitized(self):
        self.app.schema_snapshot = {'fields': [{'key': 'applicant_full_name', 'type': 'text'}]}
        now = datetime(2026, 10, 15, 9, 30, tzinfo=dt_timezone.utc)
        self.assertEqual(copy_filename(self.app, now), 'Synthetic Applicant Training Loan KES 100000 15-10-2026 12-30-00.pdf')
        self.assertEqual(copy_filename(self.app, now, document_name='Guarantee / form'),
            'Synthetic Applicant Training Loan KES 100000 Guarantee form 15-10-2026 12-30-00.pdf')

    def test_api_passes_selection_and_native_get_head_recheck_live_access(self):
        request = RequestFactory().post('/download/', {'revision': 1, 'document_key': 'guarantee',
            'client_request_id': 'api-copy'}, content_type='application/json')
        request.origination_user, request.origination_access = self.actor, user_access(self.actor, 'loan_origination')
        result = portal_origination_prepare_download(request, self.app.pk)
        self.assertEqual(result.status_code, 200, result.content)
        url = json.loads(result.content)['download_url']
        response = portal_origination_download(RequestFactory().get(url))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(PdfReader(BytesIO(response.content)).pages), 1)
        self.assertIn('Guarantee', response['Content-Disposition'])
        self.assertEqual(response['Cache-Control'], 'no-store, private')
        head = portal_origination_download(RequestFactory().head(url))
        self.assertEqual(head.content, b'')
        self.assertEqual(head['Content-Length'], str(len(response.content)))
        self.actor.is_active = False
        self.actor.save(update_fields=['is_active'])
        self.assertEqual(portal_origination_download(RequestFactory().get(url)).status_code, 403)

    def test_other_workflow_grant_does_not_authorize_document_download(self):
        outsider = get_user_model().objects.create_user('synthetic-portal-only')
        AccessGrant.objects.create(user=outsider, workflow='jawabu_portal', role='IT')
        with self.assertRaises(OriginationError):
            prepare_copy(application_id=self.app.pk, actor=outsider, revision=1, request_id='denied', document_key='primary')

    def test_revoked_origination_grant_invalidates_link(self):
        actor = get_user_model().objects.create_user('synthetic-scoped-copy')
        for capability in ['origination.view', 'origination.create']:
            WorkflowRoleCapability.objects.update_or_create(workflow='loan_origination', role='JBL_OFFICER',
                capability_key=capability, defaults={'effect': 'allow', 'enabled': True})
        grant = AccessGrant.objects.create(user=actor, workflow='loan_origination', role='JBL_OFFICER', branch='Training')
        self.app.officer = actor
        self.app.save(update_fields=['officer'])
        token, _ = prepare_copy(application_id=self.app.pk, actor=actor, revision=1, request_id='scoped', document_key='primary')
        url = reverse('loan_origination_download') + '?token=' + token
        self.assertEqual(portal_origination_download(RequestFactory().get(url)).status_code, 200)
        grant.delete()
        self.assertEqual(portal_origination_download(RequestFactory().get(url)).status_code, 403)

    def test_choices_are_only_exposed_to_full_detail_views(self):
        self.assertEqual([item['document_key'] for item in serialize_application(self.app, actor=self.actor)['download_choices']],
                         ['', 'primary', 'guarantee', 'home_visit'])
        self.assertNotIn('download_choices', serialize_application(self.app, presentation='masked'))
        self.assertNotIn('download_choices', serialize_application(self.app, include_payload=False))

    @override_settings(ORIGINATION_WEBAPP_REQUIRE_TELEGRAM_AUTH=True)
    def test_prepare_requires_authentication(self):
        response = self.client.post(reverse('loan_origination_prepare_download', args=[self.app.pk]),
            {'revision': 1, 'document_key': 'primary'}, content_type='application/json')
        self.assertEqual(response.status_code, 403)
