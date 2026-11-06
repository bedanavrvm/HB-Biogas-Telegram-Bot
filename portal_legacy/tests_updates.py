"""Update review through signed HTTP; no production providers or customer fixtures."""
from io import BytesIO
from decimal import Decimal
from openpyxl import Workbook
from django.test import TestCase, override_settings
from django.utils import timezone
from core.models import JawabuFarmerMaster, IntegrationOperation
from core.tests_telegram_authentication import BOT_TOKEN
from .models import LegacyBatch, LegacyRow, LegacyDraft, LegacyEvent
from .tests import LegacyHTTPMixin
from .updates import equivalent


def source(rows, *, eco=False):
    book=Workbook();sheet=book.active;sheet.title='Eco-conserve' if eco else 'Master Data'
    sheet.append(['Name','ID NUMBER','First Phone Number','Village','Deposit Paid to HBG','Additional Comments'])
    for row in rows:sheet.append(row)
    out=BytesIO();book.save(out);return out.getvalue()


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN,PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,
    SECURE_SSL_REDIRECT=False,REQUIRE_MINIAPP_IDEMPOTENCY_KEY=True)
class UpdateImportTests(LegacyHTTPMixin,TestCase):
    def setUp(self):
        super().setUp()
        self.group.workflow={**self.group.workflow,'master_sync_enabled':True};self.group.save(update_fields=['workflow'])
        self.case=JawabuFarmerMaster.objects.create(group_configuration=self.group, customer_name='SYNTHETIC CLIENT',
            national_id='12345678',primary_phone='254712345678',village='OLD VILLAGE',deposit_paid_hbg=Decimal('5000'),
            jbl_visit_date=timezone.localdate(),legacy_fulfillment_partner='HB')
        self.batch=LegacyBatch.objects.create(group=self.group,namespace='original',source_hash='a'*64,created_by=self.actor)
        self.original=LegacyRow.objects.create(batch=self.batch,source_sheet='Master Data',source_row=99,source_hash='a'*64,
            values={'customer_name':self.case.customer_name,'national_id':self.case.national_id,'primary_phone':self.case.primary_phone,
                'village':'OLD VILLAGE','deposit_paid_hbg':'5000','case_comment_history':'ORIGINAL NOTE'},proposal={},farmer=self.case,
            committed_at=timezone.now(),publication_ready=True,continuation_confirmed=True)

    def create(self,*args,**kwargs):
        upload,content=super().create(*args,**kwargs)
        # The mode is persisted before receiving any bytes, exactly as create API does.
        from .models import LegacyUpload
        LegacyUpload.objects.filter(pk=upload['id']).update(mode='updates')
        upload=self.request(upload=upload,method='get',query='?summary=1')['upload']
        return upload,content

    def stage_update(self,rows):
        upload=self.stage(source(rows))
        return self.finish(upload,'comparing')

    def rows(self,upload,filter_by='all'):
        return self.request(upload=upload,method='get',query='?filter='+filter_by)['rows']

    def apply(self,upload):
        upload=self.request('commit',upload=upload)['upload']
        return self.finish(upload,'committing')

    def test_only_real_changes_bulk_apply_and_resume_without_deletion(self):
        untouched=JawabuFarmerMaster.objects.create(group_configuration=self.group,customer_name='UNMENTIONED',national_id='77777777')
        upload=self.stage_update([['SYNTHETIC CLIENT','12345678','0712345678','NEW VILLAGE',5000,'ORIGINAL NOTE']])
        row=self.rows(upload)[0]
        self.assertEqual(row['proposal']['kind'],'changed')
        self.assertEqual(set(row['proposal']['changes']),{'village'})
        self.assertFalse(upload['frozen']);self.assertFalse(upload['state'].get('cleanup_complete'))
        upload=self.request('select',{'all':True,'approved':True},upload=upload)['upload']
        upload=self.apply(upload)
        self.case.refresh_from_db();self.assertEqual(self.case.village,'NEW VILLAGE')
        self.assertEqual(JawabuFarmerMaster.objects.count(),2)
        self.assertTrue(JawabuFarmerMaster.objects.filter(pk=untouched.pk).exists())
        self.original.refresh_from_db();self.assertEqual(self.original.values['village'],'OLD VILLAGE')
        self.assertEqual(LegacyEvent.objects.filter(action='fields_updated').count(),1)
        upload=self.apply(upload)
        self.assertEqual(LegacyEvent.objects.filter(action='fields_updated').count(),1)
        self.assertEqual(upload['committed'],1)
        self.assertTrue(IntegrationOperation.objects.filter(source_id=str(self.case.pk)).exists())
        for action in ['cleanup_preview','cleanup_confirm','projection_preview','projection_confirm','restart_projection']:
            self.request(action,upload=upload,status=409)

    def test_unchanged_skipped_blank_unselected_and_selected_fields_only(self):
        upload=self.stage_update([['SYNTHETIC CLIENT','12345678','0712345678','OLD VILLAGE',5000,'ORIGINAL NOTE']])
        self.assertEqual(upload['counts'],{'unchanged':1})
        upload=self.request('select',{'all':True,'approved':True},upload=upload)['upload']
        self.assertEqual(upload['selected'],0)
        upload=self.stage_update([['SYNTHETIC CLIENT','12345678','0712345678',None,5000,'NEW NOTE']])
        row=self.rows(upload)[0]
        self.assertEqual(row['reconciliation']['selected_fields'],['case_comment_history'])
        upload=self.request('select',{'all':True,'approved':True},upload=upload)['upload']
        upload=self.apply(upload)
        self.case.refresh_from_db();self.assertEqual(self.case.village,'OLD VILLAGE')
        from core.services.jawabu_comments import master_comment_history
        self.assertEqual(master_comment_history(self.case),'NEW NOTE')
        self.assertGreater(self.case.workflow_revision,1)

    def test_concurrent_case_edit_is_held_then_recomparison_is_required(self):
        upload=self.stage_update([['SYNTHETIC CLIENT','12345678','0712345678','NEW VILLAGE',5000,'ORIGINAL NOTE']])
        self.case.workflow_revision+=1;self.case.village='APP CORRECTION';self.case.save()
        upload=self.request('select',{'all':True,'approved':True},upload=upload)['upload'];upload=self.apply(upload)
        self.case.refresh_from_db();self.assertEqual(self.case.village,'APP CORRECTION')
        self.assertIn('changed since comparison',self.rows(upload)[0]['proposal']['commit_error'])
        upload=self.request('recompare',{'ids':[self.rows(upload)[0]['id']]},upload=upload)['upload']
        self.assertEqual(self.rows(upload)[0]['proposal']['changes']['village']['before'],'APP CORRECTION')

    def test_duplicate_units_and_other_register_cannot_be_silently_matched(self):
        JawabuFarmerMaster.objects.create(group_configuration=self.group,customer_name='OTHER UNIT',national_id='12345678',primary_phone='254700000001',legacy_fulfillment_partner='HB')
        JawabuFarmerMaster.objects.create(group_configuration=self.other,customer_name='PRIVATE',national_id='55555555')
        JawabuFarmerMaster.objects.create(group_configuration=self.group,customer_name='ECO CLIENT',national_id='66666666',legacy_fulfillment_partner='ECOCONSERVE')
        upload=self.stage_update([['SYNTHETIC CLIENT','12345678','0712345678','NEW',5000,'ORIGINAL NOTE'],['PRIVATE','55555555'],['ECO CLIENT','66666666']])
        rows=self.rows(upload)
        self.assertEqual(rows[0]['proposal']['case_id'],str(self.case.pk))
        self.assertEqual([r['proposal']['kind'] for r in rows[1:]],['new','new'])
        self.assertFalse(rows[1]['existing_cases']);self.assertFalse(rows[2]['existing_cases'])

    def test_new_case_requires_explicit_confirmation_and_not_select_all(self):
        upload=self.stage_update([['NEW SYNTHETIC CLIENT','87654321','0712345670','NEW VILLAGE',5000]])
        upload=self.request('select',{'all':True,'approved':True},upload=upload)['upload']
        self.assertEqual(upload['selected'],0)
        row=self.rows(upload)[0]
        upload=self.request('select',{'rows':[{'id':row['id'],'approved':True,'create_new':True}]},upload=upload)['upload']
        upload=self.apply(upload)
        self.assertEqual(upload['committed'],1)
        self.assertEqual(JawabuFarmerMaster.objects.count(),2)
        self.assertTrue(LegacyDraft.objects.get(pk=row['id']).reconciliation['operations'])

    def test_update_mode_create_contract_and_independent_authority(self):
        import hashlib
        content=source([['CLIENT','12345678']])
        body={'group_id':self.group.pk,'namespace':'mode-contract','filename':'new.xlsx','size':len(content),'digest':hashlib.sha256(content).hexdigest(),'mode':'updates'}
        upload=self.request(body=body)['upload'];self.assertEqual(upload['mode'],'updates')
        self.assertEqual(self.request(body=body)['upload']['id'],upload['id'])
        self.request('stage',{'mode':'initial'},upload=upload,status=409)
        self.staff(role='IT',workflow='complaint_cases')
        self.request(upload=upload,method='get',status=403)

    def test_equivalence_and_swapped_headers(self):
        from .updates import bind_update_headers
        mapping=bind_update_headers(['Name','Jawabu Visit Date','Decision/Action','Homebiogas Visit Date','Constituency'])
        self.assertEqual(mapping[2],'legacy_outcome');self.assertEqual(mapping[3],'hbg_visit_date')
        self.assertEqual(mapping[4],'legacy:Constituency')
        self.assertEqual(equivalent('primary_phone','0712345678'),equivalent('primary_phone','254712345678'))
        self.assertEqual(equivalent('deposit_paid_hbg','KES 5,000'),equivalent('deposit_paid_hbg','5000.00'))

    def test_original_identity_cleanup_is_not_undone_by_unchanged_raw_cells(self):
        import hashlib
        from .models import LegacyUpload, LegacyChunk
        book=Workbook();sheet=book.active;sheet.title='Master Data Compare'
        sheet.append(['Source Row','B | Customer Name | Cleaned','Z | ID NUMBER | Original','Z | National ID | Cleaned'])
        sheet.append([99,'SYNTHETIC CLIENT','12345678 / SECOND CONTACT','12345678'])
        out=BytesIO();book.save(out);content=out.getvalue();digest=hashlib.sha256(content).hexdigest()
        original=LegacyUpload.objects.create(batch=self.batch,actor=self.actor,filename='reviewed.xlsx',digest=digest,size=len(content),source_sheet='Master Data')
        LegacyChunk.objects.create(upload=original,position=0,content=content,digest=digest)
        LegacyDraft.objects.create(upload=original,source_row=99,values=self.original.values,proposal={},legacy=self.original)
        upload=self.stage_update([['SYNTHETIC CLIENT','12345678 / SECOND CONTACT','0712345678','OLD VILLAGE',5000,'ORIGINAL NOTE']])
        self.assertEqual(upload['counts'],{'unchanged':1})
        self.assertNotIn('update_private',upload['state'])

    def test_cached_formula_values_read_without_executing_formula(self):
        from .test_support import edit_worksheet
        content=source([['SYNTHETIC CLIENT','12345678','0712345678','OLD VILLAGE',5000,'ORIGINAL NOTE']])
        content=edit_worksheet(content,lambda xml:xml.replace(b'<c r="E2" t="n"><v>5000</v></c>',b'<c r="E2"><f>2500+2500</f><v>5000</v></c>'))
        upload=self.finish(self.stage(content),'comparing')
        self.assertEqual(upload['counts'],{'unchanged':1})

    def test_historical_receipt_update_publishes_new_revision_and_retains_original(self):
        upload=self.stage_update([['SYNTHETIC CLIENT','12345678','0712345678','OLD VILLAGE','KES 6,000','ORIGINAL NOTE']])
        upload=self.request('select',{'all':True,'approved':True},upload=upload)['upload'];upload=self.apply(upload)
        self.case.refresh_from_db();self.assertEqual(self.case.deposit_paid_hbg,6000)
        self.original.refresh_from_db();self.assertEqual(self.original.values['deposit_paid_hbg'],'5000')
        self.assertEqual(upload['committed'],1)

    def test_app_created_case_keeps_its_origin_and_saved_evidence_cannot_be_discarded(self):
        case=JawabuFarmerMaster.objects.create(group_configuration=self.group,customer_name='APP CLIENT',national_id='55555555',primary_phone='254712345602',village='OLD')
        upload=self.stage_update([['APP CLIENT','55555555','0712345602','NEW']])
        upload=self.request('select',{'all':True,'approved':True},upload=upload)['upload'];upload=self.apply(upload)
        case.refresh_from_db();self.assertEqual(case.village,'NEW')
        self.assertFalse(case.legacy_records.exists())
        self.request('discard',upload=upload,status=409)

    def test_historical_installation_and_commissioning_use_hb_action_validators(self):
        from hb_operations.models import HomeBiogasAction
        action=HomeBiogasAction.objects.create(farmer=self.case,legacy_origin=self.original,source_order_number='HB-1',source_requisition_version=0)
        book=Workbook();sheet=book.active;sheet.title='Master Data'
        sheet.append(['Name','ID NUMBER','Installation Status','Installation Date','Commissioning Status','Commissioning Date'])
        sheet.append(['SYNTHETIC CLIENT','12345678','Installed','01-09-2026','Commissioned','02-10-2026'])
        out=BytesIO();book.save(out)
        upload=self.finish(self.stage(out.getvalue()),'comparing')
        upload=self.request('select',{'all':True,'approved':True},upload=upload)['upload'];upload=self.apply(upload)
        self.assertEqual(upload['committed'],1,self.rows(upload))
        action.refresh_from_db();self.assertEqual(action.installation_status,'installed');self.assertEqual(action.commissioning_status,'commissioned')
        self.assertEqual(action.commissioning_date.isoformat(),'2026-10-02')

    def test_publication_follows_later_app_revision_without_sticking_on_superseded_attempt(self):
        upload=self.stage_update([['SYNTHETIC CLIENT','12345678','0712345678','NEW VILLAGE',5000,'ORIGINAL NOTE']])
        upload=self.request('select',{'all':True,'approved':True},upload=upload)['upload'];upload=self.apply(upload)
        draft=LegacyDraft.objects.get(upload_id=upload['id'])
        old=IntegrationOperation.objects.get(pk=draft.reconciliation['operations'][0])
        old.status='succeeded';old.metadata={**old.metadata,'result':{'action':'superseded'}};old.save()
        self.case.refresh_from_db();self.case.workflow_revision+=1;self.case.village='LATER APP EDIT';self.case.save()
        upload=self.request('sync_rows',upload=upload)['upload']
        upload=self.request('advance',upload=upload)['upload']
        draft.refresh_from_db()
        self.assertNotEqual(draft.reconciliation['operations'],[str(old.pk)])
        self.assertEqual(draft.reconciliation['superseded_operations'],[str(old.pk)])

    def test_amended_historical_receipt_survives_later_initial_projection(self):
        from .services import legacy_jbl_receipt
        from .projection import record_values
        book=Workbook();sheet=book.active;sheet.title='Master Data'
        sheet.append(['Name','ID NUMBER','Deposit Paid to JBL']);sheet.append(['SYNTHETIC CLIENT','12345678','KES 6,000'])
        out=BytesIO();book.save(out)
        upload=self.finish(self.stage(out.getvalue()),'comparing')
        upload=self.request('select',{'all':True,'approved':True},upload=upload)['upload'];upload=self.apply(upload)
        self.assertEqual(upload['committed'],1,self.rows(upload))
        self.assertEqual(legacy_jbl_receipt(self.case)['amount'],'6000.00')
        values=record_values(self.original,['Deposit Paid to JBL','Total'],1)
        self.assertEqual(Decimal(values[0]),6000);self.assertEqual(Decimal(values[1]),11000)

    def test_duplicate_source_match_can_be_resolved_to_one_selected_row(self):
        upload=self.stage_update([['SYNTHETIC CLIENT','12345678','0712345678','NEW VILLAGE'],['SYNTHETIC CLIENT','12345678','0712345678','OTHER VILLAGE']])
        rows=self.rows(upload);self.assertEqual([r['proposal']['kind'] for r in rows],['ambiguous','ambiguous'])
        upload=self.request('select',{'rows':[{'id':rows[0]['id'],'existing_case_id':str(self.case.pk),'approved':True}]},upload=upload)['upload']
        upload=self.apply(upload)
        self.assertEqual(upload['committed'],1)
        self.case.refresh_from_db();self.assertEqual(self.case.village,'NEW VILLAGE')
