"""Current Operations API contract; external integrations remain mocked."""
import json
from datetime import date
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase, RequestFactory, override_settings
from django.utils import timezone
from core.models import GroupSheetConfiguration, JawabuFarmerMaster, RequisitionBatch, DocumentPhysicalSignoff, InvoiceUploadBatch
from core.api import portal_views as views
from requisitions.models import OrderSequenceState, OrderWorkbookVersion
from payments.models import PaymentReceiptBatch, PaymentReceiptItem


@override_settings(RUNNING_TESTS=True, SECURE_SSL_REDIRECT=False)
class OperationsApiTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_user(username='synthetic-operations', is_superuser=True)
        self.group = GroupSheetConfiguration.objects.create(group_id='-100-synthetic-operations', enabled=True, workflow={'type': 'jawabu_homebiogas'})
        self.sequence = OrderSequenceState.objects.create(group_configuration=self.group, partner='HB', next_number=10)
        self.factory = RequestFactory()

    def request(self, method, payload=None, query=''):
        request = (self.factory.post('/synthetic/', json.dumps(payload or {}), content_type='application/json')
                   if method == 'POST' else self.factory.get('/synthetic/' + query))
        request.portal_user = self.actor
        from core.services.telegram_identity import user_access
        request.portal_access = user_access(self.actor, 'jawabu_portal')
        return request

    def farmer(self, number):
        return JawabuFarmerMaster.objects.create(customer_name=f'Training Applicant {number}',
            national_id=f'9999999{number}', group_configuration=self.group, county='Kiambu',
            branch='Limuru', final_decision='Approved', imab_created=True, customer_no=f'TRAIN-{number}',
            sub_county='Limuru', village='Training village', workflow_state='order')

    def preview(self, farmer, **extra):
        request = self.request('POST', {'farmer_ids': [str(farmer.pk)], 'requisition_date': '2026-10-06', **extra})
        with patch('core.services.jawabu_approvals.require_effective_approval'):
            response = views.portal_requisition_preview(request)
        self.assertEqual(response.status_code, 200, response.content)
        return json.loads(response.content)

    def generate(self, preview, key):
        request = self.request('POST', {'preview_token': preview['preview_token'], 'client_request_id': key})
        def assign(farmer, **values):
            farmer.order_number = values['order_number']
            farmer.requisition_date = values['requisition_date']
            farmer.workflow_revision += 1
            farmer.save()
            return True, ''
        with patch('core.services.jawabu_approvals.require_effective_approval'), \
             patch('core.services.requisition.requisition_template_for_partner', return_value=None), \
             patch('core.services.requisition.generate_requisition_excel', return_value=b'synthetic-workbook'), \
             patch('core.services.jawabu_pipeline.assign_order', side_effect=assign):
            response = views.portal_requisition_finalize(request)
        self.assertEqual(response.status_code, 200, response.content)
        return json.loads(response.content)

    def test_options_readonly_partner_and_invalid_partner(self):
        eco = OrderSequenceState.objects.create(group_configuration=self.group, partner='ECOCONSERVE', next_number=3)
        for partner, expected in [('HB', 'HB-10'), ('ECOCONSERVE', 'ECO-3')]:
            response = views.portal_requisition_options(self.request('GET', query=f'?partner={partner}'))
            self.assertEqual(json.loads(response.content)['order_number'], expected)
        self.sequence.refresh_from_db()
        eco.refresh_from_db()
        self.assertEqual((self.sequence.next_number, eco.next_number), (10, 3))
        self.assertEqual(views.portal_requisition_options(self.request('GET', query='?partner=unknown')).status_code, 400)

    def test_explicit_append_retains_versions_and_replays_after_later_amendment(self):
        first, second = self.farmer(1), self.farmer(2)
        initial_preview = self.preview(first)
        generated = self.generate(initial_preview, 'training-generate')
        batch = RequisitionBatch.objects.get(pk=generated['batch']['id'])
        unselected = self.preview(second)
        self.assertEqual(unselected['ready_count'], 1)
        self.assertEqual(unselected['append_candidates'][0]['id'], str(batch.pk))
        selected = self.preview(second, append_batch_id=str(batch.pk))
        self.assertEqual(selected['ready_count'], 2)
        appended = self.generate(selected, 'training-append')
        self.assertEqual(appended['batch']['id'], str(batch.pk))
        self.assertEqual(appended['batch']['version'], 2)
        self.assertEqual(OrderWorkbookVersion.objects.filter(batch=batch).count(), 2)
        replay = self.generate(initial_preview, 'training-generate')
        self.assertTrue(replay['idempotent_replay'])
        self.sequence.refresh_from_db()
        self.assertEqual(self.sequence.next_number, 11)
        for farmer in (first, second):
            farmer.refresh_from_db()
            self.assertEqual(farmer.requisition_batch_id, batch.pk)

    def test_signed_order_is_not_append_candidate(self):
        first = self.farmer(1)
        batch = RequisitionBatch.objects.get(pk=self.generate(self.preview(first), 'training-sign')['batch']['id'])
        DocumentPhysicalSignoff.objects.create(document_type='requisition', requisition_batch=batch,
            source_version=batch.version, source_checksum=batch.content_checksum, status='signed_approved',
            uploaded_by=self.actor, approved_by=self.actor, approved_at=timezone.now(), scan_checksum='a'*64)
        preview = self.preview(self.farmer(2))
        self.assertEqual(preview['append_candidates'], [])

    def test_archive_endpoint_post_and_replay_preserve_invoice_items(self):
        receipt = PaymentReceiptBatch.objects.create(group_configuration=self.group)
        upload = InvoiceUploadBatch.objects.create(group_configuration=self.group, original_filename='synthetic.pdf')
        item = PaymentReceiptItem.objects.create(receipt_batch=receipt, source_upload=upload)
        request = self.request('POST', {'archived': True, 'revision': 1, 'client_request_id': 'training-archive'})
        response = views.portal_invoice_receipt_archive(request, receipt.pk)
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(views.portal_invoice_receipt_archive(request, receipt.pk).status_code, 200)
        receipt.refresh_from_db()
        self.assertIsNotNone(receipt.archived_at)
        self.assertTrue(PaymentReceiptItem.objects.filter(pk=item.pk).exists())

    def test_empty_retained_membership_never_uses_shared_number(self):
        farmer = self.farmer(1)
        farmer.order_number = 'HB-10'
        farmer.save(update_fields=['order_number'])
        self.assertEqual(views._farmers_for_batch('HB-10', []), [])

    def test_invalid_preview_selection_is_clean_validation(self):
        for payload in [[], {'farmer_ids': ['invalid']}, {'farmer_ids': 'invalid'}]:
            response = views.portal_requisition_preview(self.request('POST', payload))
            self.assertEqual(response.status_code, 400)

    def test_receipt_scope_checks_every_case_and_unknown_identity(self):
        from core.services.telegram_identity import user_access
        from core.services.access_grant_governance import governed_access_grant_mutation
        from core.models import AccessGrant
        scoped_actor = get_user_model().objects.create_user(username='synthetic-branch-operations')
        with governed_access_grant_mutation('Synthetic scope regression fixture'):
            AccessGrant.objects.create(user=scoped_actor, workflow='jawabu_portal', role='IT',
                branch='Limuru', group_configuration=self.group)
        receipt = PaymentReceiptBatch.objects.create(group_configuration=self.group)
        upload = InvoiceUploadBatch.objects.create(group_configuration=self.group, original_filename='synthetic.pdf')
        PaymentReceiptItem.objects.create(receipt_batch=receipt, source_upload=upload)
        request = self.request('GET')
        request.portal_user = scoped_actor
        request.portal_access = user_access(scoped_actor, 'jawabu_portal')
        self.assertEqual(views.portal_invoice_receipt_batch_detail(request, receipt.pk).status_code, 403)
        self.assertEqual(json.loads(views.portal_invoice_receipt_batches(request).content)['batches'], [])
