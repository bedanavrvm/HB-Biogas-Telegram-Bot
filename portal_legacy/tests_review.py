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
    def test_missing_historical_id_is_imported_with_a_visible_resolvable_quality_warning(self):
        from core.services.jawabu_case360 import serialize_case360
        from core.services.jawabu_validation import refresh_data_quality_issues, validation_warnings
        upload=self.commit(self.stage(workbook_bytes([[2,'HISTORICAL NAME','712345678','']])))
        farmer=JawabuFarmerMaster.objects.get()
        self.assertEqual(farmer.national_id,'')
        self.assertIsNone(farmer.customer_id)
        self.assertTrue(farmer.data_quality_issues.filter(field_name='national_id',code='review_required',active=True).exists())
        self.assertIn('Historical National ID is missing',str(serialize_case360(farmer)['validation']))
        farmer.national_id='87654321';farmer.save(update_fields=['national_id'])
        refresh_data_quality_issues(farmer)
        self.assertFalse(farmer.data_quality_issues.filter(code='review_required',active=True).exists())
        self.assertFalse(any(x['field']=='national_id' for x in validation_warnings(farmer)))

    def test_potential_units_keep_source_ids_without_confirming_customer_or_unit_links(self):
        from core.models import JawabuCustomer
        from core.services.jawabu_validation import refresh_data_quality_issues, validation_warnings
        from .models import LegacyEvent, LegacyRow
        from .services import commit_row
        from core.services.telegram_identity import user_access
        customer=JawabuCustomer.objects.create(national_id='12345678')
        upload=self.stage(workbook_bytes([[2,'FIRST HISTORY','712345678','12345678'],[3,'OTHER HISTORY','712345679','12345678']]))
        upload=self.cleanup(upload)
        selected=[{'id':r['id'],'approved':True,'potential_additional_unit':True,
                   'note':'Repeated historical ID; distinct unit not confirmed.',
                   'review_flags':[{'field':'installation_date','code':'legacy_source_conflict',
                                    'message':'Dates disagree. Ask Portal IT to verify the source.'}]} for r in self.rows(upload)]
        upload=self.request('select',{'rows':selected},upload=upload)['upload']
        upload=self.request('commit',upload=upload)['upload'];upload=self.finish(upload,'committing')
        self.assertEqual(JawabuFarmerMaster.objects.count(),2)
        for farmer in JawabuFarmerMaster.objects.all():
            self.assertEqual(farmer.national_id,'12345678')
            self.assertIsNone(farmer.customer_id)
            refresh_data_quality_issues(farmer)
            self.assertEqual({x['code'] for x in validation_warnings(farmer)}, {'potential_additional_unit','legacy_source_conflict'})
            issue=farmer.data_quality_issues.get(code='legacy_source_conflict')
            issue.active=False;issue.save(update_fields=['active'])
            refresh_data_quality_issues(farmer)
            self.assertNotIn('legacy_source_conflict',{x['code'] for x in validation_warnings(farmer)})
        self.assertEqual(customer.applications.count(),0)
        for row in LegacyRow.objects.all():
            commit_row(row.pk,expected_revision=row.revision,request_key='replay:'+str(row.pk),actor=self.actor,
                       access=user_access(self.actor,'jawabu_portal'),potential_additional_unit=True,
                       separate_unit_note='Repeated historical ID; distinct unit not confirmed.')
        self.assertEqual(JawabuFarmerMaster.objects.count(),2)
        self.assertEqual(LegacyEvent.objects.filter(action='imported').count(),2)
        self.assertTrue(all(e.payload['potential_additional_unit'] for e in LegacyEvent.objects.filter(action='imported')))

    def test_review_flags_cannot_bypass_identity_requirements_or_authorization(self):
        upload=self.cleanup(self.stage(workbook_bytes([[2,'REVIEW NAME','712345678','']])))
        row=self.rows(upload)[0]
        for value in ('true',1):
            self.request('select',{'rows':[{'id':row['id'],'approved':True,'potential_additional_unit':value}]},upload=upload,status=409)
        for flag in ({'field':'national_id','code':'arbitrary','message':'x'},
                     {'field':'national_id','code':'legacy_source_conflict','message':''}):
            self.request('select',{'rows':[{'id':row['id'],'approved':True,'review_flags':[flag]}]},upload=upload,status=409)
        upload=self.request('select',{'rows':[{'id':row['id'],'approved':True,'potential_additional_unit':True,'note':'Unconfirmed'}]},upload=upload)['upload']
        upload=self.request('commit',upload=upload)['upload']
        upload=self.finish(upload,'committing')
        self.assertEqual(JawabuFarmerMaster.objects.count(),0)
        self.assertIn('requires its reported National ID',LegacyDraft.objects.get(pk=row['id']).proposal['commit_error'])
        self.staff(role='IT',workflow='complaint_cases')
        self.request('select',{'rows':[{'id':row['id'],'approved':True}]},upload=upload,status=403)

    def test_identity_correction_clears_old_reconciliation_review_selection(self):
        upload=self.stage(workbook_bytes([[2,'REVIEW NAME','712345678','12345678']]))
        row=self.rows(upload)[0]
        upload=self.request('select',{'rows':[{'id':row['id'],'approved':True,'potential_additional_unit':True,
                     'note':'Unconfirmed repeated ID','review_flags':[{'field':'national_id','code':'legacy_source_conflict','message':'Verify with Portal IT.'}]}]},upload=upload)['upload']
        upload=self.request('edit',{'id':row['id'],'changes':{'national_id':'87654321'}},upload=upload)['upload']
        audit=LegacyDraft.objects.get(pk=row['id']).reconciliation
        self.assertNotIn('potential_additional_unit',audit)
        self.assertNotIn('review_flags',audit)
        self.assertFalse(self.rows(upload)[0]['approved'])

    def test_invalid_flag_in_bulk_selection_rolls_back_earlier_selections(self):
        upload=self.stage(workbook_bytes([[2,'FIRST REVIEW','712345678','12345678'],[3,'OTHER REVIEW','712345679','87654321']]))
        rows=self.rows(upload)
        self.request('select',{'rows':[{'id':rows[0]['id'],'approved':True},
            {'id':rows[1]['id'],'approved':True,'potential_additional_unit':'true'}]},upload=upload,status=409)
        self.assertFalse(LegacyDraft.objects.filter(upload_id=upload['id'],approved=True).exists())

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
