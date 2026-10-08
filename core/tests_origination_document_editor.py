"""Independent authoring contracts, using synthetic PDFs and mocked storage."""
from copy import deepcopy
import hashlib
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import Product
from core.tests_origination_templates import synthetic_pdf
from origination.models import OriginationDocumentTemplate, OriginationDocumentProductEligibility
from origination.services.document_editor import create_document, readiness, save_signers, copy_document, publish_document
from origination.services.origination_templates import initial_template_configuration, save_calibration_draft


@override_settings(GOOGLE_DRIVE_MEDIA_FOLDER_ID='synthetic-folder')
class DocumentEditorTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser('editor-test', 'editor@example.test', 'test-only')
        self.client.force_login(self.actor)
        self.pdf = synthetic_pdf()
        self.source_patch = patch('origination.services.origination_templates.load_template_source', return_value=self.pdf)
        self.source_patch.start()
        self.addCleanup(self.source_patch.stop)
        storage = patch('core.services.order_approval.GoogleDriveMediaStorage')
        storage.start().return_value.download.return_value = self.pdf
        self.addCleanup(storage.stop)
        self.document = OriginationDocumentTemplate.objects.create(name='Synthetic document', document_type='test-document',
            version=1, document_role='primary', document_key='primary', status='ready',
            form_schema={'fields':[], 'sections':[]}, signer_rules=[],
            source_filename='synthetic.pdf', source_sha256=hashlib.sha256(self.pdf).hexdigest(),
            source_byte_size=len(self.pdf), page_count=1, drive_file_id='synthetic-drive',
            placement_config=initial_template_configuration(None, form_schema={'fields':[]}), created_by=self.actor)
        self.document.placement_config.update(document_type=self.document.document_type,version=1)
        self.document.save(update_fields=['placement_config'])

    def save(self, rules, key='signers-1', schema=0, revision=0, configuration=None):
        return save_signers(document=self.document, rules=rules, actor=self.actor, schema_revision=schema,
            revision=revision, configuration=configuration or deepcopy(self.document.placement_config), request_id=key)

    def ready(self):
        document = self.save([{'role':'borrower','label':'Borrower','required':True}])
        config = deepcopy(document.configuration_revisions.latest('revision').configuration)
        config['field_overlay_manifest']['fields'] = {field['key']:{'context_key':field['key'], 'page_number':1,
            'box':{'x':10,'y':20+index*20,'width':120,'height':14}} for index,field in enumerate(document.form_schema['fields'])}
        config['signature_overlay_manifest']['slots'] = {'borrower.signature':{'role':'borrower','slot_key':'signature',
            'slot_type':'signature','page_number':1,'box':{'x':10,'y':150,'width':120,'height':30}}}
        save_calibration_draft(template=document, configuration=config, actor=self.actor, expected_revision=1, client_request_id='placement-1')
        self.document.refresh_from_db()
        return self.document

    def test_empty_document_can_add_edit_remove_signers(self):
        document = self.save([{'role':'borrower','label':'Borrower','required':True}])
        self.assertEqual(document.form_schema['fields'][1]['type'], 'phone')
        self.assertEqual(document.form_schema['fields'][2]['type'], 'national_id')
        self.assertTrue(any(task['key'] == 'signature:borrower.signature' for task in readiness(document)['tasks']))
        config=document.configuration_revisions.latest('revision').configuration
        document=self.save([],key='remove',schema=1,revision=1,configuration=config)
        self.assertEqual(document.signer_rules, [])
        self.assertTrue(any(task['key'] == 'signers' for task in readiness(document)['tasks']))

    def test_save_retry_is_idempotent_and_different_retry_rejected(self):
        rules=[{'role':'borrower','required':True}]
        self.save(rules)
        self.save(rules)
        self.assertEqual(self.document.configuration_revisions.count(),1)
        with self.assertRaises(ValidationError): self.save([{'role':'officer'}])

    def test_stale_schema_rejects_without_losing_saved_work(self):
        self.save([{'role':'officer'}])
        with self.assertRaises(ValidationError): self.save([{'role':'borrower'}],key='other-tab')
        self.document.refresh_from_db()
        self.assertEqual(self.document.signer_rules[0]['role'],'officer')

    def test_duplicate_or_unknown_roles_rejected(self):
        for rules in [[{'role':'unknown'}],[{'role':'borrower'},{'role':'borrower'}]]:
            with self.assertRaises(ValidationError): self.save(rules)
        self.assertFalse(self.document.configuration_revisions.exists())

    def test_readiness_does_not_download_pdf(self):
        self.ready()
        with patch('origination.services.origination_templates.load_template_source', side_effect=AssertionError('External read')):
            self.assertTrue(readiness(self.document)['can_publish'])
            response=self.client.get(reverse('admin:origination_document_readiness',args=[self.document.pk]))
            self.assertEqual(response.status_code,200)

    def test_publish_and_replay_keep_same_document(self):
        self.ready()
        from origination.services.origination_setup_documents import shared_review
        token=shared_review(self.document)['token']
        published=publish_document(document=self.document,actor=self.actor,revision=2,request_id='publish',impact_token=token)
        self.assertEqual(published.status,'active')
        replay=publish_document(document=self.document,actor=self.actor,revision=2,request_id='publish',impact_token=token)
        self.assertEqual(replay.pk,published.pk)
        self.assertEqual(self.document.events.filter(action='editor_published').count(),1)
        with self.assertRaises(ValidationError): self.save([{'role':'borrower'}],key='after-publish')

    def test_product_only_copy_does_not_replace_other_product(self):
        source=self.ready()
        source.status='active';source.published_configuration_revision=source.configuration_revisions.latest('revision');source.save()
        first=Product.objects.create(code='copy-one',name='Copy one')
        second=Product.objects.create(code='copy-two',name='Copy two')
        for product in [first,second]: OriginationDocumentProductEligibility.objects.create(template=source,product=product,created_by=self.actor)
        copy=copy_document(source=source,actor=self.actor,request_id='copy',product_id=first.pk,replace=True)
        self.assertEqual(list(copy.eligible_products.all()),[first])
        self.assertEqual(source.eligible_products.count(),2)
        from origination.services.origination_setup_documents import shared_review
        publish_document(document=copy,actor=self.actor,revision=1,request_id='copy-publish',impact_token=shared_review(copy)['token'])
        self.assertFalse(source.eligible_products.filter(pk=first.pk).exists())
        self.assertTrue(source.eligible_products.filter(pk=second.pk).exists())
        self.assertEqual(copy_document(source=source,actor=self.actor,request_id='copy',product_id=first.pk,replace=True).pk,copy.pk)

    def test_shared_update_requires_current_review_token(self):
        source=self.ready();source.status='active';source.published_configuration_revision=source.configuration_revisions.latest('revision');source.save()
        product=Product.objects.create(code='shared-product',name='Shared product')
        OriginationDocumentProductEligibility.objects.create(template=source,product=product,created_by=self.actor)
        from origination.services.origination_templates import clone_reusable_template_version
        draft,_=clone_reusable_template_version(source,actor=self.actor)
        revision=draft.configuration_revisions.latest('revision').revision
        with self.assertRaises(ValidationError):
            publish_document(document=draft,actor=self.actor,revision=revision,request_id='shared',impact_token='old-token')
        source.refresh_from_db();self.assertEqual(source.status,'active')

    def test_new_pdf_retry_does_not_create_extra_document_or_upload(self):
        with patch('origination.services.origination_templates._upload_template_bytes',return_value=('synthetic-new','https://example.test/pdf')) as upload:
            def create(name='New PDF'):
                return create_document(actor=self.actor,request_id='new-pdf',source=None,name=name,role='primary',products=[],
                    pdf=SimpleUploadedFile('synthetic.pdf',self.pdf,content_type='application/pdf'))
            first=create();second=create()
            self.assertEqual(first.pk,second.pk);self.assertEqual(upload.call_count,1)
            with self.assertRaises(ValidationError): create('Different name')

    def test_non_superuser_cannot_access_editor_writes(self):
        user=get_user_model().objects.create_user('regular-editor',is_staff=True)
        with self.assertRaises(PermissionDenied): copy_document(source=self.document,actor=user,request_id='forbidden')
        self.client.force_login(user)
        for name in ['origination_document_new','origination_document_readiness','origination_document_signers']:
            response=self.client.get(reverse('admin:'+name,args=[] if name.endswith('_new') else [self.document.pk]))
            self.assertEqual(response.status_code,403)

    def test_draft_product_can_select_document_without_becoming_active(self):
        from core.models import ProductVersion
        from origination.models import OriginationProductDefinition
        from origination.document_editor_admin import NewDocumentForm
        product=Product.objects.create(code='draft-editor-product',name='Draft product',active=False)
        version=ProductVersion.objects.create(product=product,version=1)
        OriginationProductDefinition.objects.create(product_version=version,product_key=product.code,
            name=product.name,version=1,lifecycle_status='draft')
        self.assertIn(product,NewDocumentForm().fields['products'].queryset)
        document=save_signers(document=self.document,rules=[{'role':'borrower'}],actor=self.actor,
            schema_revision=0,revision=0,configuration=self.document.placement_config,request_id='draft-product',
            details={'name':'Draft LAF','products':[str(product.pk)]},field_pack='lending')
        self.assertIn('loan_amount',[f['key'] for f in document.form_schema['fields']])
        self.assertIn('repayment_tenor',[f['key'] for f in document.form_schema['fields']])
        self.assertTrue(document.eligible_products.filter(pk=product.pk).exists())
        product.refresh_from_db();self.assertFalse(product.active)

    def test_shared_publication_replaces_current_document_for_all_allowed_products(self):
        source=self.ready();source.status='active';source.published_configuration_revision=source.configuration_revisions.latest('revision');source.save()
        products=[Product.objects.create(code=f'shared-{n}',name=f'Shared {n}') for n in range(2)]
        for product in products: OriginationDocumentProductEligibility.objects.create(template=source,product=product)
        from origination.services.origination_templates import clone_reusable_template_version
        from origination.services.origination_setup_documents import shared_review
        draft,_=clone_reusable_template_version(source,actor=self.actor)
        publish_document(document=draft,actor=self.actor,revision=1,request_id='all-products',impact_token=shared_review(draft)['token'])
        source.refresh_from_db();draft.refresh_from_db()
        self.assertEqual(source.status,'retired');self.assertEqual(draft.status,'active')
        self.assertEqual(set(draft.eligible_products.all()),set(products))
        self.assertEqual(source.form_schema,draft.form_schema)

    def test_malformed_layout_has_a_repair_task_not_a_server_error(self):
        self.document.placement_config['field_overlay_manifest']=[]
        self.document.placement_config['signature_overlay_manifest']={'slots':['bad']}
        result=readiness(self.document)
        self.assertFalse(result['can_publish'])
        self.assertIn('layout',[t['key'] for t in result['tasks']])

    def test_copy_retry_is_bound_to_actor(self):
        source=self.ready()
        copied=copy_document(source=source,actor=self.actor,request_id='copy-actor')
        other=get_user_model().objects.create_superuser('other-editor','other@example.test','test-only')
        with self.assertRaises(ValidationError):
            copy_document(source=source,actor=other,request_id='copy-actor')
        self.assertEqual(copy_document(source=source,actor=self.actor,request_id='copy-actor').pk,copied.pk)

    def test_copy_form_supports_existing_ready_documents(self):
        from origination.document_editor_admin import NewDocumentForm
        self.assertIn(self.document,NewDocumentForm().fields['source'].queryset)

    def test_new_copy_retry_stays_content_bound_after_publication(self):
        source=self.ready()
        args=dict(actor=self.actor,request_id='created-copy',source=source,name='Copied document',
                  role='primary',products=[],pdf=None)
        copied=create_document(**args)
        copied.status='active';copied.save(update_fields=['status'])
        self.assertEqual(create_document(**args).pk,copied.pk)
        with self.assertRaises(ValidationError):
            create_document(**{**args,'name':'Changed retry'})
