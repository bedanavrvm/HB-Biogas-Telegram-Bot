"""Corrections preserve source evidence and cannot alter imported cases."""
from django.test import TestCase, override_settings
from core.models import JawabuFarmerMaster
from core.tests_telegram_authentication import BOT_TOKEN
from .models import LegacyDraft
from .tests import LegacyHTTPMixin
from .test_support import workbook_bytes


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN,PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,
    SECURE_SSL_REDIRECT=False,MINIAPP_TEST_DELETION_ENABLED=True,REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True)
class LegacyReviewTests(LegacyHTTPMixin,TestCase):
    def test_blocked_correction_is_durable_audited_and_requires_new_approval(self):
        upload=self.stage(workbook_bytes([[2,'REVIEWED NAME','712345678','12345678','bad']]))
        row=self.rows(upload)[0]
        self.assertEqual(row['proposal']['review_status'],'blocked')
        upload=self.request('edit',{'id':row['id'],'changes':{'deposit_paid_hbg':'5000'}},upload=upload)['upload']
        saved=self.rows(upload)[0]
        self.assertEqual(saved['source_values']['deposit_paid_hbg'],'5000')
        self.assertEqual(saved['original_values']['deposit_paid_hbg'],'bad')
        self.assertEqual(saved['proposal']['review_status'],'ready')
        self.assertFalse(saved['approved'])
        draft=LegacyDraft.objects.get(pk=row['id'])
        self.assertEqual(draft.reconciliation['corrections'][0]['actor_id'],self.actor.pk)
        upload=self.request('select',{'rows':[{'id':row['id'],'approved':True}]},upload=upload)['upload']
        self.assertEqual(self.rows(upload)[0]['original_values']['deposit_paid_hbg'],'bad')
        upload=self.request('edit',{'id':row['id'],'changes':{'customer_name':'CONFIRMED NAME'}},upload=upload)['upload']
        self.assertFalse(self.rows(upload)[0]['approved'])
        upload=self.commit(upload)
        self.assertEqual(JawabuFarmerMaster.objects.get().deposit_paid_hbg,5000)
        self.assertEqual(self.rows(upload)[0]['original_values']['customer_name'],'REVIEWED NAME')
        self.request('edit',{'id':row['id'],'changes':{'customer_name':'REWRITE'}},upload=upload,status=409)

    def test_correction_trust_boundaries_and_revision_conflicts(self):
        upload=self.stage();other=self.stage(workbook_bytes([[9,'OTHER FILE']]))
        row=self.rows(upload)[0];foreign=self.rows(other)[0]
        for changes in ({'source_row':'99'},{'workflow_state':'ordered'},{'group_configuration':'99'}):
            self.request('edit',{'id':row['id'],'changes':changes},upload=upload,status=409)
        self.request('edit',{'id':foreign['id'],'changes':{'customer_name':'FOREIGN'}},upload=upload,status=404)
        changed=self.request('edit',{'id':row['id'],'changes':{'customer_name':'SAVED'}},upload=upload)['upload']
        self.request('edit',{'id':row['id'],'changes':{'customer_name':'STALE'}},upload=upload,status=409)
        self.assertEqual(self.rows(changed)[0]['name'],'SAVED')
        self.staff(role='IT',workflow='complaint_cases')
        self.request('edit',{'id':row['id'],'changes':{'customer_name':'DENIED'}},upload=changed,status=403)

    def test_identity_review_names_matching_values_and_excludes_self_and_other_owners(self):
        own=JawabuFarmerMaster.objects.create(group_configuration=self.group,customer_name='KNOWN CASE',national_id='12345678',primary_phone='254700000001')
        JawabuFarmerMaster.objects.create(group_configuration=self.other,customer_name='PRIVATE OTHER OWNER',national_id='12345678')
        upload=self.stage(workbook_bytes([[2,'IMPORTED NAME','712345678','12345678'],[3,'SECOND UNIT','712345679','12345678']]))
        row=self.rows(upload)[0]
        self.assertEqual(row['existing_cases'][0]['name'],'KNOWN CASE')
        self.assertEqual(row['existing_cases'][0]['national_id'],'12345678')
        self.assertEqual(row['duplicate_rows'][0]['source_row'],3)
        self.assertIn('national_id',row['field_issues'])
        self.assertNotIn('PRIVATE OTHER OWNER',str(row))
        self.assertEqual(self.request(upload=upload,method='get',query='?filter=warning')['total'],2)
        self.assertEqual(self.request(upload=upload,method='get',query='?filter=ready')['total'],0)
        upload=self.request('edit',{'id':row['id'],'changes':{'national_id':'87654321'}},upload=upload)['upload']
        self.assertFalse(self.rows(upload)[0]['identity_collision'])
        self.assertEqual(self.request(upload=upload,method='get',query='?filter=warning')['total'],1)
        self.assertEqual(self.request(upload=upload,method='get',query='?filter=ready')['total'],1)
        # Imported provenance must not flag its own canonical identity as a collision.
        from .services import row_payload
        from .models import LegacyRow, LegacyBatch
        from django.utils import timezone
        batch=LegacyBatch.objects.get(pk=LegacyDraft.objects.get(pk=row['id']).upload.batch_id)
        legacy=LegacyRow.objects.create(batch=batch,source_sheet='Master Data',source_row=99,source_hash='0'*64,
            values={'customer_name':'KNOWN CASE','national_id':'12345678'},proposal={'fields':{'national_id':'12345678'}},farmer=own,committed_at=timezone.now())
        self.assertFalse(row_payload(legacy)['identity_collision'])
