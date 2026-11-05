"""Historical imports through real signed HTTP, XLSX decoding and test DB."""
import base64
from datetime import timedelta
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import hashlib
import json
import uuid

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import Workbook, load_workbook
from core.models import AccessGrant, CaseUpdate, ComplaintCaseControl, ComplaintCaseEvent, ComplianceAuditChainState, GroupSheetConfiguration, ParsedMessage, UserProfile, IntegrationOperation
from core.services.access_grant_governance import governed_access_grant_mutation
from core.services.group_config import GroupConfig, GroupRegistry
from core.services.sheet_schema import SheetSchema
from core.services import complaint_cases
from core.tests_telegram_authentication import BOT_TOKEN, signed_init_data
from .models import ImportUpload, ImportRow


def source(rows=None, headers=None, *, revision_note=''):
    book=Workbook(); sheet=book.active; sheet.title='Case Management'
    sheet.append(headers or ['Source Row','Customer Name','Status','Date Reported','Date Resolved','Customer National ID','Primary Phone Number'])
    for row in (rows if rows is not None else [[2,'SYNTHETIC CLIENT','CLOSED','24-May-2025','','','712345678']]): sheet.append(row)
    if revision_note: book.create_sheet('Import notes').append([revision_note])
    out=BytesIO();book.save(out);book.close();return out.getvalue()


class ImportFixture:
    def setUp(self):
        super().setUp()
        ComplianceAuditChainState.objects.get_or_create(singleton=1)
        self.owner=GroupSheetConfiguration.objects.create(group_id='-100complaint-legacy-test',sheet_id='synthetic-register',sheet_name='Complaints Register',display_name='Synthetic Complaints',workflow={'type':'case'},sheet_schema={'schema_version':2})
        self.other=GroupSheetConfiguration.objects.create(group_id='-100complaint-other-test',sheet_id='other-register',workflow={'type':'case'})
        self.user=get_user_model().objects.create_user(username='complaint-legacy-it')
        self.bind(self.user,995001)
        with governed_access_grant_mutation('Synthetic Complaint import authority'):
            AccessGrant.objects.create(user=self.user,workflow='complaint_cases',role='IT',group_configuration=self.owner)
        GroupRegistry.get_instance().reload()
        self.directory=TemporaryDirectory();self.addCleanup(self.directory.cleanup)
        temp=patch('complaint_legacy.services.gettempdir',return_value=self.directory.name);temp.start();self.addCleanup(temp.stop)

    def bind(self,user,telegram_id):
        UserProfile.objects.update_or_create(user=user,defaults={'telegram_id':str(telegram_id)})
        self.headers={'HTTP_X_TELEGRAM_INIT_DATA':signed_init_data(user={'id':telegram_id})}

    def call(self,action=None,body=None,*,upload=None,status=200,method='post'):
        if upload:
            url=reverse('complaint_legacy_action',kwargs={'upload_id':upload['id'],'action':action}) if action else reverse('complaint_legacy_upload',kwargs={'upload_id':upload['id']})
        else:url=reverse('complaint_legacy_uploads')
        values={'group_id':self.owner.group_id,**(body or {})}
        if upload:values.setdefault('revision',upload['revision'])
        headers={**self.headers,'HTTP_X_REQUEST_ID':str(uuid.uuid4())}
        response=self.client.get(url,values,**headers) if method=='get' else self.client.post(url,json.dumps(values),content_type='application/json',**headers)
        self.assertEqual(response.status_code,status,response.content[:900]);return response.json()

    def create(self,data=None,**changes):
        data=data if data is not None else source()
        result=self.call(body={'namespace':'synthetic-changeover','filename':'synthetic.xlsx','source_sheet':'Case Management',
            'size':len(data),'digest':hashlib.sha256(data).hexdigest(),**changes})
        return result['upload'],data

    def stage(self,data=None,**changes):
        upload,data=self.create(data,**changes)
        for position,start in enumerate(range(0,len(data),512*1024)):
            upload=self.call('chunk',{'position':position,'content':base64.b64encode(data[start:start+512*1024]).decode()},upload=upload)['upload']
        upload=self.call('prepare',upload=upload)['upload']
        upload=self.call('stage',upload=upload)['upload']
        return self.finish(upload,'staging')

    def finish(self,upload,phase):
        for _ in range(1000):
            if upload['phase']!=phase:return upload
            upload=self.call('advance',upload=upload)['upload']
        self.fail('No bounded progress to the next import step')

    def commit(self,upload):
        upload=self.call('select',{'all':True,'approved':True},upload=upload)['upload']
        upload=self.call('commit',upload=upload)['upload']
        return self.finish(upload,'committing')

    def rows(self,upload):return self.call(upload=upload,method='get')['rows']


@override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN,COMPLAINT_CASES_WEBAPP_REQUIRE_TELEGRAM_AUTH=True,SECURE_SSL_REDIRECT=False)
class ComplaintLegacyTests(ImportFixture,TestCase):
    def test_status_and_original_reported_date_are_authoritative(self):
        data=source([[2,'SYNTHETIC','OPEN','24-May-2025','CLOSED in old notes']],headers=['Source Row','FARMER','CASE STATUS','Case Date','HBG Case Status Re-Confirmation'])
        upload=self.commit(self.stage(data));case=ParsedMessage.objects.get(source='complaint_legacy')
        self.assertEqual(case.complaint_status,'Open');self.assertEqual(timezone.localdate(case.timestamp).isoformat(),'2025-05-24')
        self.assertIsNone(case.date_resolved);self.assertEqual(upload['committed'],1)

    def test_missing_bio_location_and_description_do_not_fabricate_or_block_legacy(self):
        upload=self.stage(source([[2,'CLOSED','24-May-2025']],headers=['Source Row','Status','Date Reported']))
        row=self.rows(upload)[0];self.assertEqual(row['proposal']['status'],'warning')
        upload=self.commit(upload);case=ParsedMessage.objects.get(source='complaint_legacy')
        self.assertEqual(case.customer_id,'');self.assertEqual(case.county,'');self.assertEqual(case.customer_name,'')
        self.assertEqual(case.complaint_status,'Closed');self.assertIsNone(case.complaint_control.customer_id)
        self.assertEqual(upload['committed'],1)

    def test_closed_date_unknown_is_unknown_in_ui_and_projected_register(self):
        self.commit(self.stage());case=ParsedMessage.objects.get(source='complaint_legacy')
        data=complaint_cases.serialize_case(case)
        self.assertEqual(data['age_label'],'Closure date unknown');self.assertIsNone(data['days_open'])
        self.assertIsNone(data['sla']['resolution_hours'])
        schema=SheetSchema.from_config({'schema_version':2});row=schema.row_for_message(case)
        self.assertEqual(row[2],'24-05-25');self.assertEqual(row[3],'CLOSED')
        self.assertEqual(row[19],'');self.assertEqual(row[20],'')

    def test_invalid_status_and_reported_dates_are_blocked(self):
        for status,reported in [('Closed. Issue fixed','24-May-2025'),('','24-May-2025'),('CLOSED',''),('CLOSED','14/3/205'),('CLOSED','14.11.24/30.12.24'),('OPEN','31-Feb-2025')]:
            with self.subTest(status=status,reported=reported):
                upload=self.stage(source([[2,'SYNTHETIC',status,reported]]))
                self.assertEqual(self.rows(upload)[0]['proposal']['status'],'blocked')
                upload=self.call('select',{'all':True,'approved':True},upload=upload)['upload']
                self.assertEqual(upload['selected'],0);self.call('commit',upload=upload,status=409)
        self.assertFalse(ParsedMessage.objects.filter(source='complaint_legacy').exists())

    def test_future_or_inconsistent_dates_are_blocked(self):
        future=(timezone.localdate()+timedelta(days=2)).isoformat()
        for status,start,end in [('OPEN',future,''),('CLOSED','24-May-2025','23-May-2025'),('OPEN','24-May-2025','25-May-2025')]:
            with self.subTest(status=status,start=start,end=end):
                upload=self.stage(source([[2,'SYNTHETIC',status,start,end]]))
                self.assertEqual(self.rows(upload)[0]['proposal']['status'],'blocked')

    def test_historical_comments_keep_their_separation_and_unknown_authorship(self):
        data=source([[2,'CLOSED','24-May-2025','HB OLD NOTE','JBL VERIFICATION SOURCE','UNDATED HISTORY','JBL OLD FEEDBACK']],
                    headers=['Source Row','Status','Date Reported','Resolution Comments','JBL Verification Comments','Resolution History','Jawabu Comments  (Feedback)'])
        self.commit(self.stage(data));case=ParsedMessage.objects.get(source='complaint_legacy')
        self.assertIn('HB OLD NOTE',complaint_cases.resolution_comments_text(case))
        self.assertNotIn('JBL OLD FEEDBACK',complaint_cases.resolution_comments_text(case))
        self.assertIn('JBL VERIFICATION SOURCE',complaint_cases.verification_comments_text(case))
        self.assertIn('author/time not recorded',complaint_cases.verification_comments_text(case))
        self.assertIn('JBL OLD FEEDBACK',complaint_cases.resolution_history_text(case))
        self.assertEqual(CaseUpdate.objects.filter(parsed_message=case).count(),0)
        self.assertEqual(ComplaintCaseEvent.objects.filter(case=case.complaint_control,action='legacy_imported').count(),1)
        history=complaint_cases.complaint_history_page(case)['items']
        self.assertEqual(history[0]['action'],'legacy_imported')
        self.assertIn('HB OLD NOTE',history[0]['note']);self.assertIn('JBL OLD FEEDBACK',history[0]['note'])

    def test_new_intake_validation_is_unchanged(self):
        config=GroupConfig(**self.owner.as_group_config_kwargs());actor=complaint_cases.staff_actor_for_user(config,self.user)
        with self.assertRaises(complaint_cases.ComplaintCaseError):
            complaint_cases.validate_new_case_fields(config,actor,'new-intake-stays-strict',{'status':'Closed','date_reported':'24-May-2025'})

    def test_files_and_committed_rows_replay_without_new_cases(self):
        upload,data=self.create();replay,_=self.create(data,namespace='different-name');self.assertEqual(replay['id'],upload['id'])
        upload=self.commit(self.stage(data));self.assertEqual(upload['committed'],1)
        second=self.commit(self.stage(source(revision_note='Changed workbook metadata, identical source facts')))
        self.assertEqual(second['committed'],1);self.assertEqual(ParsedMessage.objects.filter(source='complaint_legacy').count(),1)

    def test_changed_committed_source_never_overwrites_the_case(self):
        self.commit(self.stage());upload=self.stage(source([[2,'SYNTHETIC CLIENT','OPEN','24-May-2025','','','712345678']]))
        self.assertEqual(self.rows(upload)[0]['proposal']['status'],'blocked')
        self.assertEqual(ParsedMessage.objects.get(source='complaint_legacy').complaint_status,'Closed')

    def test_duplicate_source_facts_are_held_for_review(self):
        upload=self.stage(source([[2,'SYNTHETIC','OPEN','24-May-2025'],[3,'SYNTHETIC','OPEN','24-May-2025']]))
        self.assertEqual([r['proposal']['status'] for r in self.rows(upload)],['warning','blocked'])
        self.assertEqual(self.commit(upload)['committed'],1)

    def test_duplicates_remain_held_across_staging_checkpoints(self):
        data=source([[i+2,f'SYNTHETIC {i}','OPEN','24-May-2025'] for i in range(250)]+
                    [[252,'SYNTHETIC 0','OPEN','24-May-2025']])
        upload=self.stage(data)
        self.assertEqual(ImportRow.objects.get(upload_id=upload['id'],source_row=252).proposal['status'],'blocked')
        upload=self.call('select',{'all':True,'approved':True},upload=upload)['upload']
        self.assertEqual(upload['selected'],250)

    def test_normalized_and_extra_phones_preserve_original_source(self):
        upload=self.stage(source([[2,'SYNTHETIC','OPEN','24-May-2025','','','0712345678/0712345679']]))
        row=self.rows(upload)[0]
        self.assertEqual(row['values']['customer_phone'],'0712345678/0712345679')
        self.assertEqual(row['proposal']['fields']['customer_phone'],'254712345678')

    def test_authorization_and_independent_workflow_scope(self):
        for workflow,role in [('jawabu_portal','IT'),('loan_origination','IT'),('complaint_cases','OFFICER'),('complaint_cases','MANAGER')]:
            with self.subTest(workflow=workflow,role=role):
                user=get_user_model().objects.create_user(username=uuid.uuid4().hex)
                with governed_access_grant_mutation('Synthetic denied import fixture'):
                    AccessGrant.objects.create(user=user,workflow=workflow,role=role,group_configuration=self.owner)
                self.bind(user,user.pk+995000);self.call(method='get',status=403)
        self.assertFalse(ImportUpload.objects.exists())

    def test_unsigned_and_other_owner_requests_are_denied(self):
        self.headers={};self.call(method='get',status=403)
        self.bind(self.user,995001)
        self.call(method='get',body={'group_id':self.other.group_id},status=403)

    def test_conflicting_chunk_and_stale_revision_have_no_side_effects(self):
        upload,data=self.create();encoded=base64.b64encode(data).decode()
        upload=self.call('chunk',{'position':0,'content':encoded},upload=upload)['upload']
        self.call('chunk',{'position':0,'content':encoded},upload=upload)
        self.call('chunk',{'position':0,'content':base64.b64encode(b'X'+data[1:]).decode()},upload=upload,status=409)
        self.call('prepare',{'revision':upload['revision']-1},upload=upload,status=409)
        self.assertFalse(ImportRow.objects.exists())

    def test_imports_are_bounded_and_resume_without_duplicate_cases(self):
        upload=self.stage(source([[i+2,f'SYNTHETIC {i}','OPEN','24-May-2025'] for i in range(61)]))
        upload=self.call('select',{'all':True,'approved':True},upload=upload)['upload']
        upload=self.call('commit',upload=upload)['upload'];upload=self.call('advance',upload=upload)['upload']
        self.assertGreater(upload['committed'],0);self.assertLessEqual(upload['committed'],50)
        self.client=type(self.client)();upload=self.finish(upload,'committing')
        self.assertEqual(upload['committed'],61);self.assertEqual(ParsedMessage.objects.filter(source='complaint_legacy').count(),61)

    def test_sheet_publication_starts_automatically_and_is_durable(self):
        upload=self.commit(self.stage())
        self.assertEqual(upload['queued'],1)
        self.assertEqual(IntegrationOperation.objects.filter(operation_type='complaint_browser.sheet',status='pending').count(),1)
        self.assertEqual(upload['synced'],0)
        self.assertEqual(upload['awaiting_sync'],1)

    def test_uncommitted_discard_reopens_and_committed_provenance_is_retained(self):
        from .services import cache_root
        data=source();upload=self.stage(data);cached=cache_root(ImportUpload.objects.get(pk=upload['id']))
        self.assertTrue(cached.exists());self.call('discard',upload=upload);self.assertFalse(cached.exists())
        revived,_=self.create(data);self.assertEqual(revived['phase'],'uploading')
        upload=self.commit(self.stage(data));self.call('discard',upload=upload,status=409)
        self.assertEqual(ImportRow.objects.filter(case__isnull=False).count(),1)

    def test_template_matches_the_actual_projected_register(self):
        response=self.client.get(reverse('complaint_legacy_template'),{'group_id':self.owner.group_id},**self.headers)
        self.assertEqual(response.status_code,200)
        book=load_workbook(BytesIO(response.content));headers=[c.value for c in book['Case Management'][1]]
        self.assertEqual(headers[:4],['#','Complaint ID','Date Reported','Status'])
        self.assertEqual(headers[17:22],['Resolution Comments','JBL Verification Comments','Date Resolved','Days Open','Resolution History'])
        self.assertEqual(len(headers),23);self.assertEqual(headers[-1],'Source Row');book.close()

    def test_live_lease_blocks_other_commands_and_expired_lease_recovers(self):
        upload=self.stage()
        ImportUpload.objects.filter(pk=upload['id']).update(lease=uuid.uuid4(),lease_until=timezone.now()+timedelta(seconds=60))
        self.call('select',{'all':True,'approved':True},upload=upload,status=409)
        ImportUpload.objects.filter(pk=upload['id']).update(lease_until=timezone.now()-timedelta(seconds=1))
        self.assertEqual(self.commit(upload)['committed'],1)

    def test_foreign_upload_and_row_ids_cannot_be_selected(self):
        upload=self.stage();row=self.rows(upload)[0]
        other=self.stage(source([[20,'SYNTHETIC OTHER','OPEN','24-May-2025']]))
        changed=self.call('select',{'rows':[{'id':row['id'],'approved':True}]},upload=other)['upload']
        self.assertEqual(changed['selected'],0);self.assertFalse(ImportRow.objects.get(pk=row['id']).approved)
        self.call(upload=upload,method='get',body={'group_id':self.other.group_id},status=403)

    def test_source_formulas_and_conflicting_headers_never_become_status_or_dates(self):
        for data,conflicting_headers in [(source([[2,'OPEN','=TODAY()']],headers=['Source Row','Status','Date Reported']),False),
                     (source([[2,'OPEN','CLOSED','24-May-2025']],headers=['Source Row','Status','CASE STATUS','Date Reported']),True)]:
            upload,bytes_=self.create(data)
            upload=self.call('chunk',{'position':0,'content':base64.b64encode(bytes_).decode()},upload=upload)['upload']
            if conflicting_headers:
                self.call('prepare',upload=upload,status=409);continue
            result=self.call('prepare',upload=upload)
            if result['upload']['phase']=='mapping':
                upload=self.call('stage',upload=result['upload'])['upload'];self.call('advance',upload=upload,status=409)
            else:self.fail('An invalid workbook was treated as ready')

    def test_bad_checksum_and_zip_are_controlled_and_create_no_cases(self):
        for data,digest in [(b'not-an-xlsx',hashlib.sha256(b'not-an-xlsx').hexdigest()),(source(),'0'*64)]:
            upload,_=self.create(data,digest=digest)
            upload=self.call('chunk',{'position':0,'content':base64.b64encode(data).decode()},upload=upload)['upload']
            self.call('prepare',upload=upload,status=409)
        self.assertFalse(ParsedMessage.objects.filter(source='complaint_legacy').exists())

    def test_original_unmapped_cells_and_extreme_formatted_dimensions_are_preserved(self):
        data=source([[2,'OPEN','24-May-2025','KEEP HISTORICAL CELL']],headers=['Source Row','Status','Date Reported',''])
        book=load_workbook(BytesIO(data));book.active.cell(1033,16381).number_format='0'
        out=BytesIO();book.save(out);book.close()
        upload=self.stage(out.getvalue());row=self.rows(upload)[0]
        self.assertEqual(row['values']['unmapped:4'],'KEEP HISTORICAL CELL');self.assertEqual(upload['total'],1)

    def test_location_limits_block_cleanly_and_long_historical_description_is_retained(self):
        data=source([[2,'OPEN','24-May-2025','X'*129,'Historical detail '*400]],
            headers=['Source Row','Status','Date Reported','County','Complaint Description'])
        upload=self.stage(data);row=self.rows(upload)[0]
        self.assertEqual(row['proposal']['status'],'blocked');self.assertIn('128',row['proposal']['issues'][0])
        self.assertEqual(row['values']['county'],'X'*129)
        upload=self.stage(source([[3,'OPEN','24-May-2025','Historical detail '*400]],
            headers=['Source Row','Status','Date Reported','Complaint Description']))
        self.assertEqual(self.commit(upload)['committed'],1)
        self.assertGreater(len(ParsedMessage.objects.get(source='complaint_legacy').complaint_description),5000)

    def test_normal_publisher_outputs_the_22_column_register_and_replays_by_cmp_id(self):
        from complaint_publications.worker import publish
        from core.services.sheet_schema import COMPLAINT_REGISTER_FIELD_HEADERS
        upload=self.commit(self.stage(source([[2,'CLOSED','24-May-2025','HB NOTE','JBL CHECK']],
            headers=['Source Row','Status','Date Reported','Resolution Comments','JBL Verification Comments'])))
        class Sheet:
            schema=SheetSchema.from_config({'schema_version':2});_sheet_id='synthetic-register';_sheet_name='Complaints Register'
            def __init__(self):self.rows={}
            def validate_sheet_structure(self):return True,''
            def append_row(self,row,key):self.rows.setdefault(key,list(row));return True
            def update_case_row(self,key,values):
                headers=list(COMPLAINT_REGISTER_FIELD_HEADERS)
                for field,value in values.items():self.rows[key][headers.index(field)]=value
                return True
        sheet=Sheet();job=IntegrationOperation.objects.get(operation_type='complaint_browser.sheet')
        with patch('core.services.complaint_cases.get_sheets_service',return_value=sheet),patch('core.services.sheets.get_sheets_service',return_value=sheet):
            publish(job);publish(job)
        job.refresh_from_db();self.assertEqual(job.status,'succeeded');self.assertEqual(len(sheet.rows),1)
        row=next(iter(sheet.rows.values()));self.assertEqual(len(row),22);self.assertTrue(row[1].startswith('CMP-'))
        self.assertEqual(row[2],'24-05-25');self.assertEqual(row[3],'CLOSED');self.assertEqual(row[19:21],['',''])
        self.assertIn('HB NOTE',row[17]);self.assertNotIn('JBL CHECK',row[17]);self.assertIn('JBL CHECK',row[18])
