"""Synthetic acceptance for streamlined identity evidence and application lifecycle."""
from io import BytesIO
from decimal import Decimal
from unittest.mock import patch
import hashlib

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, SimpleTestCase, override_settings, RequestFactory, TransactionTestCase
from django.db import connection, close_old_connections, transaction
from unittest import skipUnless
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from pypdf import PdfReader, PdfWriter

from core.models import ComplianceAuditEvent, IntegrationOperation, AccessGrant
from core.services.number_words import number_words
from origination import tests_identity_copies as identity_fixtures
from core import tests_origination_document_editor as editor_fixtures
from core.tests_jbl_visit_documents import photo
from origination.models import LoanOriginationApplication, OriginationProductDefinition, OriginationSigningPackage, OriginationSigningAction
from origination.services.identity_copies import combine_identity_files
from origination.services.application_lifecycle import remove_application
from origination.services.loan_origination import OriginationError, OriginationConflict


def pdf(pages=1, encrypted=False):
    writer=PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=595,height=842)
    if encrypted:
        writer.encrypt('synthetic')
    out=BytesIO();writer.write(out)
    return SimpleUploadedFile('synthetic.pdf',out.getvalue(),content_type='application/pdf')


class WordsTests(SimpleTestCase):
    def test_values_use_decimal_and_english_without_rounding(self):
        for value, expected in [('150,000','One Hundred And Fifty Thousand'),('0','Zero'),
                ('1001','One Thousand And One'),('-12.05','Minus Twelve Point Zero Five'),
                (Decimal('150000.00'),'One Hundred And Fifty Thousand'),('1.230','One Point Two Three Zero')]:
            with self.subTest(value=value): self.assertEqual(number_words(value),expected)
        for value in ('NaN','Infinity','invalid','1e30'):
            with self.assertRaises(ValueError): number_words(value)

    def test_pdf_uses_placement_format_and_rejects_overflow(self):
        from core.services.partnership_laf_preview import render_template, PartnershipLafPreviewError
        base={'page_number':1,'box':{'x':20,'y':30,'width':500,'height':30},'context_key':'amount','font_size':10}
        config={'field_overlay_manifest':{'fields':{'digits':base,'words':{**base,'value_format':'number_words',
            'box':{**base['box'],'y':90}}}}}
        payload={'amount':'150000'}
        result=PdfReader(BytesIO(render_template(pdf().read(),config,payload)))
        text=result.pages[0].extract_text()
        self.assertIn('One Hundred And Fifty Thousand',text);self.assertIn('150000',text)
        self.assertEqual(payload['amount'],'150000')
        config['field_overlay_manifest']['fields']['words']['box']['width']=10
        with self.assertRaises(PartnershipLafPreviewError): render_template(pdf().read(),config,payload)

    def test_words_do_not_round_under_a_low_decimal_context_precision(self):
        from decimal import localcontext
        with localcontext() as context:
            context.prec=3
            self.assertEqual(number_words(Decimal('150000.0123456789')),
                'One Hundred And Fifty Thousand Point Zero One Two Three Four Five Six Seven Eight Nine')


class MixedIdentityTests(SimpleTestCase):
    def test_mixed_sources_keep_order_and_are_deterministic(self):
        files=[photo('one.jpg',1),pdf(2),photo('two.jpg',2)]
        first=combine_identity_files(files).read();second=combine_identity_files(files).read()
        reader=PdfReader(BytesIO(first))
        self.assertEqual(len(reader.pages),4)
        self.assertEqual(first,second)
        self.assertEqual(int(reader.pages[1].mediabox.width),595)

    def test_combined_pdf_and_single_image_are_accepted(self):
        for files,count in [([pdf(2)],2),([photo('combined.jpg',1)],1)]:
            self.assertEqual(len(PdfReader(combine_identity_files(files)).pages),count)

    def test_limits_and_invalid_sources_fail_before_storage(self):
        for files in [[],[pdf() for _ in range(11)],[pdf(21)],[pdf(encrypted=True)],
                      [SimpleUploadedFile('broken.pdf',b'%PDF-damaged',content_type='application/pdf')]]:
            with self.assertRaises(OriginationError): combine_identity_files(files)


class IdentityReplacementTests(TestCase):
    setUp=identity_fixtures.IdentityEvidenceTests.setUp

    def upload(self, request_id, content):
        from origination.services.origination_evidence import upload_requirement_evidence
        self.app.refresh_from_db()
        with patch('core.services.order_approval.GoogleDriveMediaStorage') as storage:
            storage.return_value.upload.return_value=('synthetic-file','https://example.test/private')
            item,_=upload_requirement_evidence(application_id=self.app.pk,actor=self.actor,requirement_key='borrower_id_copy',
                expected_revision=self.app.revision,request_id=request_id,file_obj=content)
        return item

    def test_successful_replacement_keeps_one_current_copy_and_audit(self):
        one=self.upload('one',pdf())
        two=self.upload('two',pdf(2))
        one.refresh_from_db();self.assertEqual(one.status,'removed');self.assertEqual(two.status,'uploaded')
        self.assertTrue(one.drive_file_id)
        self.assertEqual(self.app.requirement_evidence_files.filter(status='uploaded').count(),1)
        self.assertEqual(self.app.events.filter(action='identity_copy_replaced').count(),2)

    def test_upload_failure_keeps_previous_copy(self):
        from origination.services.origination_evidence import upload_requirement_evidence
        one=self.upload('one',pdf());self.app.refresh_from_db()
        with patch('core.services.order_approval.GoogleDriveMediaStorage') as storage:
            storage.return_value.upload.side_effect=OSError('synthetic unavailable')
            two,_=upload_requirement_evidence(application_id=self.app.pk,actor=self.actor,requirement_key='borrower_id_copy',
                expected_revision=self.app.revision,request_id='two',file_obj=pdf(2))
        one.refresh_from_db();self.assertEqual(one.status,'uploaded');self.assertEqual(two.status,'failed')


class LifecycleTests(TestCase):
    def setUp(self):
        self.actor=get_user_model().objects.create_superuser('synthetic-lifecycle',password='synthetic')
        self.product=OriginationProductDefinition.objects.create(product_key='synthetic-life',name='Synthetic')
        self.app=LoanOriginationApplication.objects.create(product_definition=self.product,officer=self.actor,
            reference_number='SYNTHETIC-LIFECYCLE',branch='Synthetic',schema_snapshot={'fields':[]})

    def remove(self, **overrides):
        return remove_application(**{**dict(application_id=self.app.pk,actor=self.actor,
            expected_revision=self.app.revision,request_id='synthetic-lifecycle'),**overrides})

    def test_unsigned_deletion_is_durable_replay_and_preserves_product(self):
        pk=self.app.pk
        result=self.remove();self.assertTrue(result['deleted']);self.assertFalse(LoanOriginationApplication.objects.filter(pk=pk).exists())
        self.assertTrue(self.remove()['replayed']);self.assertTrue(OriginationProductDefinition.objects.filter(pk=self.product.pk).exists())
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='application.deleted').count(),1)

    def test_signed_application_requires_reason_and_retains_original_bytes(self):
        content=pdf().read();digest=hashlib.sha256(content).hexdigest()
        package=OriginationSigningPackage.objects.create(application=self.app,application_revision=1,
            external_reference='synthetic-life-package',status='fully_signed',signed_document_hash=digest,
            pending_signed_document=content,document_type='synthetic')
        with self.assertRaises(OriginationConflict):self.remove()
        with self.assertRaises(OriginationError):self.remove(invalidate=True)
        result=self.remove(invalidate=True,reason='Synthetic duplicate')
        self.assertEqual(result['status'],'invalidated');package.refresh_from_db()
        self.assertEqual(bytes(package.pending_signed_document),content);self.assertEqual(package.signed_document_hash,digest)
        self.assertTrue(self.remove(invalidate=True,reason='Synthetic duplicate')['replayed'])
        self.app.refresh_from_db();self.assertEqual(self.app.status,'invalidated')
        from origination.services.application_copies import copy_content
        self.assertEqual(copy_content(self.app)[0],content)

    def test_recalled_draft_with_old_signature_cannot_be_deleted(self):
        package=OriginationSigningPackage.objects.create(application=self.app,application_revision=1,
            external_reference='synthetic-old-package',document_type='synthetic')
        OriginationSigningAction.objects.create(package=package,document_key='primary',slot_key='signature',
            signer_role='borrower',action_type='signature',mode='verified',request_id='synthetic-old-action')
        with self.assertRaises(OriginationConflict):self.remove()

    def test_stale_revision_and_other_officer_cannot_delete(self):
        self.app.revision=5;self.app.save(update_fields=['revision'])
        with self.assertRaises(OriginationConflict): self.remove(expected_revision=1)
        other=get_user_model().objects.create_user('synthetic-other')
        AccessGrant.objects.create(user=other,workflow='loan_origination',role='JBL_OFFICER',branch='Synthetic')
        with self.assertRaises(PermissionDenied):self.remove(actor=other)

    def test_owner_and_scoped_it_have_separate_workflow_authority(self):
        owner=get_user_model().objects.create_user('synthetic-owner')
        AccessGrant.objects.create(user=owner,workflow='loan_origination',role='JBL_OFFICER',branch='Synthetic')
        self.app.officer=owner;self.app.save(update_fields=['officer'])
        self.assertTrue(self.remove(actor=owner)['deleted'])

    def test_lifecycle_endpoint_checks_method_and_replays_after_delete(self):
        from origination.views import portal_origination_delete_draft
        import json
        request=RequestFactory().get('/synthetic/');request.origination_user=self.actor
        self.assertEqual(portal_origination_delete_draft(request,str(self.app.pk)).status_code,405)
        request=RequestFactory().post('/synthetic/',data=json.dumps({'revision':1,'request_id':'endpoint-life'}),content_type='application/json',HTTP_IDEMPOTENCY_KEY='endpoint-life')
        request.origination_user=self.actor;request.origination_access=None
        first=portal_origination_delete_draft(request,str(self.app.pk))
        self.assertEqual(first.status_code,200,first.content)
        self.assertEqual(portal_origination_delete_draft(request,str(self.app.pk)).status_code,200)

    def test_it_scope_does_not_transfer_from_another_workflow_or_branch(self):
        tech=get_user_model().objects.create_user('synthetic-tech')
        AccessGrant.objects.create(user=tech,workflow='tat_tracker',role='IT')
        with self.assertRaises(PermissionDenied):self.remove(actor=tech)
        grant=AccessGrant.objects.create(user=tech,workflow='loan_origination',role='IT',branch='Elsewhere')
        with self.assertRaises(PermissionDenied):self.remove(actor=tech)
        grant.branch='Synthetic';grant.save(update_fields=['branch'])
        self.assertTrue(self.remove(actor=tech)['deleted'])

    def test_partial_signing_is_frozen_and_old_link_and_jobs_close(self):
        from origination.models import OriginationSignerSession
        from origination.services.origination_esign import resolve_session
        from django.utils import timezone
        from datetime import timedelta
        from origination.services.application_copies import copy_content
        package=OriginationSigningPackage.objects.create(application=self.app,application_revision=1,
            external_reference='synthetic-partial',document_type='synthetic',status='in_progress',
            frozen_unsigned_document=pdf().read())
        package.unsigned_document_hash=hashlib.sha256(bytes(package.frozen_unsigned_document)).hexdigest();package.save()
        OriginationSigningAction.objects.create(package=package,document_key='primary',slot_key='signature',
            signer_role='borrower',action_type='signature',mode='verified',request_id='synthetic-partial-sign')
        session=OriginationSignerSession.objects.create(package=package,signer_role='borrower',
            token_hash=hashlib.sha256(b'synthetic-token').hexdigest(),token_expires_at=timezone.now()+timedelta(hours=1),created_by=self.actor)
        op=IntegrationOperation.objects.create(integration='telegram',operation_type='origination_approval_alert',
            source_model=package._meta.label,source_id=str(package.pk),deduplication_key='synthetic-cancel')
        self.remove(invalidate=True,reason='Synthetic correction')
        session.refresh_from_db();op.refresh_from_db();self.app.refresh_from_db()
        self.assertFalse(session.is_active);self.assertEqual(op.status,'dead_letter')
        self.assertTrue(copy_content(self.app)[0])
        with self.assertRaises(OriginationError):resolve_session('synthetic-token')

    def test_deletion_rolls_back_when_independent_audit_fails(self):
        with patch('origination.services.application_lifecycle.record_event',side_effect=RuntimeError('synthetic audit failure')):
            with self.assertRaises(RuntimeError):self.remove()
        self.assertTrue(LoanOriginationApplication.objects.filter(pk=self.app.pk).exists())

    def test_closed_signed_app_is_hidden_unless_archived_filter_is_selected(self):
        from origination.views import portal_origination_applications
        import json
        self.app.status='invalidated';self.app.save(update_fields=['status'])
        def listing(params):
            request=RequestFactory().get('/api/origination/api/applications/',params)
            request.origination_user=self.actor;request.origination_access=None
            return json.loads(portal_origination_applications(request).content)
        self.assertEqual(listing({})['pagination']['total'],0)
        self.assertEqual(listing({'status_group':'archived'})['pagination']['total'],1)


class LegacySignatureAuthoringTests(TestCase):
    def test_legacy_draft_registers_copied_signature_before_validating_layout(self):
        from copy import deepcopy
        from core import tests_origination_document_editor as fixtures
        from origination.services.document_editor import save_signers
        from origination.services.origination_fields import template_form_contract
        fixtures.DocumentEditorTests.setUp(self)
        document=fixtures.DocumentEditorTests.ready(self)
        owner=OriginationProductDefinition.objects.create(product_key='legacy-copy',name='Legacy editable',
            form_schema=document.form_schema,signer_rules=document.signer_rules)
        document.product_definition=owner;document.save(update_fields=['product_definition'])
        config=deepcopy(document.configuration_revisions.latest('revision').configuration)
        rules=deepcopy(owner.signer_rules)
        rules[0]['slots'] += [{'key':'borrower_signature_copy','type':'signature','required':True},
            {'key':'borrower_signature_copy_date','type':'date_signed','signature_key':'borrower_signature_copy','required':True}]
        for key,kind in [('borrower_signature_copy','signature'),('borrower_signature_copy_date','date_signed')]:
            config['signature_overlay_manifest']['slots']['borrower.'+key]={
                'role':'borrower','slot_key':key,'slot_type':kind,'label':'Synthetic copy','page_number':1,
                'box':{'x':20,'y':250 if kind=='signature' else 285,'width':120,'height':30}}
        before=deepcopy(owner.signer_rules)
        saved=save_signers(document=document,rules=rules,actor=self.actor,schema_revision=owner.form_schema['_revision'],
            revision=2,configuration=config,request_id='legacy-copy-slots')
        self.assertIn('borrower_signature_copy',[slot['key'] for slot in template_form_contract(saved)[1][0]['slots']])
        owner.refresh_from_db();self.assertEqual(owner.signer_rules,before)

    save = editor_fixtures.DocumentEditorTests.save


@skipUnless(connection.vendor == 'postgresql', 'PostgreSQL required for removal/signature concurrency.')
class LifecycleConcurrencyTests(TransactionTestCase):
    setUp=LifecycleTests.setUp

    def test_concurrent_duplicate_removals_commit_one_audit_and_one_replay(self):
        barrier=Barrier(2)
        def run():
            close_old_connections()
            try:
                actor=get_user_model().objects.get(pk=self.actor.pk)
                barrier.wait(timeout=15)
                return remove_application(application_id=self.app.pk,actor=actor,expected_revision=1,request_id='concurrent-removal')
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:run(),range(2)))
        self.assertEqual(sorted(result['replayed'] for result in results),[False,True])
        self.assertEqual(ComplianceAuditEvent.objects.filter(action='application.deleted').count(),1)

    def test_signature_and_deletion_cannot_both_commit(self):
        package=OriginationSigningPackage.objects.create(application=self.app,application_revision=1,
            external_reference='synthetic-race',document_type='synthetic')
        barrier=Barrier(2)
        def sign():
            close_old_connections()
            try:
                barrier.wait(timeout=15)
                with transaction.atomic():
                    app=LoanOriginationApplication.objects.select_for_update().filter(pk=self.app.pk).first()
                    if not app:return 'gone'
                    OriginationSigningAction.objects.create(package_id=package.pk,document_key='primary',slot_key='signature',
                        signer_role='borrower',action_type='signature',mode='verified',request_id='synthetic-race-sign')
                    return 'signed'
            finally:close_old_connections()
        def delete():
            close_old_connections()
            try:
                actor=get_user_model().objects.get(pk=self.actor.pk)
                barrier.wait(timeout=15)
                try:
                    remove_application(application_id=self.app.pk,actor=actor,expected_revision=1,request_id='race-removal')
                    return 'deleted'
                except OriginationConflict:return 'blocked'
            finally:close_old_connections()
        with ThreadPoolExecutor(max_workers=2) as pool:
            signing=pool.submit(sign);removing=pool.submit(delete)
            result=(signing.result(),removing.result())
        self.assertIn(result,[('signed','blocked'),('gone','deleted')])
