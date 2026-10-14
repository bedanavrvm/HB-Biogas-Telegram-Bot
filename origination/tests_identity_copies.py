from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase, RequestFactory, override_settings
from django.contrib.auth import get_user_model
from django.urls import reverse

from core.tests_jbl_visit_documents import photo, controlled_renderer
from origination.models import OriginationProductDefinition, LoanOriginationApplication
from origination.services.identity_copies import copy_options, prepare_identity_copy, collection_enabled
from origination.services.loan_origination import OriginationError, OriginationConflict, _missing_application_requirements
from origination.services.origination_evidence import upload_requirement_evidence, serialize_evidence


class IdentityCaptureTests(SimpleTestCase):
    @patch('core.services.jbl_visit_documents.render_document', side_effect=controlled_renderer)
    def test_both_sides_create_one_stable_pdf(self, renderer):
        from pypdf import PdfReader
        front, back = photo('front.jpg', 1), photo('back.jpg', 2)
        first = prepare_identity_copy(front, back)
        second = prepare_identity_copy(front, back)
        self.assertEqual(len(PdfReader(first).pages), 1)
        first.seek(0); second.seek(0)
        self.assertEqual(first.read(), second.read())
        self.assertEqual(renderer.call_args.args[0], 'CLIENT_ID')

    def test_missing_side_and_duplicate_photo_rejected(self):
        for front, back in [(photo('front.jpg', 1), None), (photo('front.jpg', 1), photo('back.jpg', 1))]:
            with self.assertRaises(OriginationError):
                prepare_identity_copy(front, back)

    def test_display_labels_do_not_bind_identity(self):
        application = SimpleNamespace(status='draft', schema_snapshot={'fields': [
            {'key':'unrelated','label':'Guarantor ID','type':'national_id'}]},
            signer_rules_snapshot=[],form_payload={'unrelated':'99000001'})
        self.assertEqual(copy_options(application), [])


class IdentityEvidenceTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username='synthetic-id-officer', is_superuser=True)
        self.other = get_user_model().objects.create_user(username='synthetic-id-other')
        self.definition = OriginationProductDefinition.objects.create(product_key='synthetic-id',name='Synthetic ID')
        self.app = LoanOriginationApplication.objects.create(product_definition=self.definition,officer=self.actor,
            reference_number='ORG-SYNTHETIC-ID', schema_snapshot={'fields':[
                {'key':'applicant_id_number','type':'national_id'}, {'key':'guarantor_id','type':'national_id'}]},
            signer_rules_snapshot=[{'role':'guarantor_1','identity_fields':{'national_id':'guarantor_id'}}],
            form_payload={'applicant_id_number':'99000001','guarantor_id':'99000002'},
            product_terms_snapshot={'requirements':[{'key':'guarantor_1_id_copy','type':'document',
                'workflow':'loan_origination','required':True,'enforcement_stage':'review'}]})

    def upload(self, key='synthetic-id-copy', actor=None):
        with patch('core.services.jbl_visit_documents.render_document',side_effect=controlled_renderer), \
             patch('core.services.order_approval.GoogleDriveMediaStorage') as storage:
            storage.return_value.upload.return_value = ('synthetic-drive-id','https://example.invalid')
            return upload_requirement_evidence(application_id=self.app.pk,actor=actor or self.actor,
                requirement_key='guarantor_1_id_copy',expected_revision=self.app.revision,
                request_id=key,file_obj=prepare_identity_copy(photo('front.jpg',1),photo('back.jpg',2)),
                provenance='front_back')

    def test_optional_roles_upload_replay_and_changed_identity(self):
        self.assertEqual([item['identity_role'] for item in copy_options(self.app)],['borrower','guarantor_1'])
        self.assertEqual(_missing_application_requirements(self.app,stage='review'),[])
        item,replayed=self.upload()
        self.assertFalse(replayed)
        duplicate,replayed=self.upload()
        self.assertTrue(replayed);self.assertEqual(item.pk,duplicate.pk)
        self.assertFalse(serialize_evidence(item)['identity_changed'])
        self.app.form_payload['guarantor_id']='99000003';self.app.save(update_fields=['form_payload'])
        item.refresh_from_db()
        self.assertTrue(serialize_evidence(item)['identity_changed'])
        self.app.refresh_from_db()
        with self.assertRaisesRegex(OriginationError,'earlier ID'):
            self.upload(key='synthetic-changed-id-copy')

    def test_wrong_actor_stale_revision_and_submitted_legacy_policy(self):
        with self.assertRaises(OriginationError): self.upload(actor=self.other)
        self.app.revision=20
        with self.assertRaises(OriginationConflict): self.upload()
        self.app.refresh_from_db();self.app.status='signing_pending';self.app.save(update_fields=['status'])
        self.assertFalse(collection_enabled(self.app))
        self.assertEqual(len(_missing_application_requirements(self.app,stage='review')),1)
        with self.assertRaises(OriginationError): self.upload()

    @override_settings(ORIGINATION_WEBAPP_REQUIRE_TELEGRAM_AUTH=False,DEBUG=True)
    def test_id_upload_requires_auth_and_preview_is_private(self):
        url=reverse('loan_origination_evidence_upload',args=[self.app.pk,'borrower_id_copy'])
        self.assertIn(self.client.post(url).status_code,(401,403))
        from origination.views import portal_origination_signature_preview
        request=RequestFactory().post('/', {'name':'Synthetic Signer','font':'caveat',
            'revision':1,'package_id':'00000000-0000-4000-8000-000000000000'},content_type='application/json')
        request.origination_user=self.other
        with patch('origination.views._application_access_error',return_value=__import__('django.http',fromlist=['JsonResponse']).JsonResponse({'ok':False},status=403)):
            self.assertEqual(portal_origination_signature_preview(request,str(self.app.pk)).status_code,403)
