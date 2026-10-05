"""Synthetic cross-workflow settings and ownership checks."""
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase, override_settings

from core.models import AccessGrant, GroupSheetConfiguration
from report_delivery.models import ReportSchedule, ApprovedRecipient
from report_delivery.services import allowed_configurations, validate_recipient
from report_delivery.settings import settings_action, save_configuration
from report_delivery.sources import capture_workflow_report


class SettingsTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='synthetic-tat-email-it')
        self.group = GroupSheetConfiguration.objects.create(group_id='synthetic-tat-email-group')
        AccessGrant.objects.create(user=self.user, workflow='tat_tracker', role='IT', group_configuration=self.group)
        self.payload = {'id': str(uuid.uuid4()), 'group_configuration': self.group.pk, 'title':'Weekly TAT',
                        'preset':'tat', 'frequency':'weekly', 'send_time':'08:00', 'active':True,
                        'recipients':['reports@example.invalid']}

    def test_it_can_configure_own_recipients_and_replay_save(self):
        first = save_configuration(self.user,'tat_tracker',self.payload)
        second = save_configuration(self.user,'tat_tracker',self.payload)
        self.assertEqual(first.pk,second.pk)
        self.assertEqual(second.revision,1)
        self.assertEqual(ReportSchedule.objects.count(),1)
        self.assertEqual(ApprovedRecipient.objects.get().workflow,'tat_tracker')
        self.assertIsNotNone(second.next_run_at)

    def test_branch_options_use_complete_current_workflow_grants(self):
        narrow = get_user_model().objects.create_user(username='synthetic-branch-options-it')
        AccessGrant.objects.create(user=narrow,workflow='tat_tracker',role='IT',branch='Nakuru',group_configuration=self.group)
        AccessGrant.objects.create(user=narrow,workflow='jawabu_portal',role='IT',branch='Meru',group_configuration=self.group)
        data=settings_action(narrow,'tat_tracker',{'action':'list'})
        self.assertEqual(data['branches_by_group'][str(self.group.pk)],[{'value':'Nakuru','label':'Nakuru'}])
        broad=settings_action(self.user,'tat_tracker',{'action':'list'})
        self.assertIn({'value':'','label':'All branches'},broad['branches_by_group'][str(self.group.pk)])

    def test_other_apps_require_their_own_it_grants(self):
        with self.assertRaises(PermissionDenied):
            save_configuration(self.user,'jawabu_portal', {**self.payload,'preset':'pipeline'})
        with self.assertRaises(PermissionDenied):
            settings_action(self.user,'complaint_cases',{'action':'list'})
        save_configuration(self.user,'tat_tracker',self.payload)
        self.assertFalse(allowed_configurations(self.user,ReportSchedule,workflow='jawabu_portal').exists())

    def test_scope_cannot_be_composed_from_different_grants(self):
        other = get_user_model().objects.create_user(username='synthetic-narrow-email-it')
        AccessGrant.objects.create(user=other,workflow='tat_tracker',role='IT',branch='A',product='X',group_configuration=self.group)
        AccessGrant.objects.create(user=other,workflow='tat_tracker',role='IT',branch='B',product='Y',group_configuration=self.group)
        with self.assertRaises(PermissionDenied):
            save_configuration(other,'tat_tracker',{**self.payload,'branch':'A','product':'Y'})

    def test_invalid_address_rolls_back_entire_save(self):
        with self.assertRaises(ValidationError):
            save_configuration(self.user,'tat_tracker',{**self.payload,'recipients':['not-an-email']})
        self.assertEqual(ReportSchedule.objects.count(),0)
        self.assertEqual(ApprovedRecipient.objects.count(),0)

    def test_stale_edit_and_wrong_preset_are_rejected(self):
        schedule=save_configuration(self.user,'tat_tracker',self.payload)
        with self.assertRaises(ValidationError):
            save_configuration(self.user,'tat_tracker',{**self.payload,'title':'Changed','revision':0})
        with self.assertRaises(ValidationError):
            save_configuration(self.user,'tat_tracker',{**self.payload,'preset':'finance','revision':schedule.revision})

    def test_recipient_approval_cannot_cross_apps(self):
        schedule=save_configuration(self.user,'tat_tracker',self.payload)
        recipient=schedule.recipients.get(); recipient.workflow='complaint_cases'
        with self.assertRaises(ValidationError):
            validate_recipient(schedule,recipient)

    @override_settings(REPORT_EMAIL_DELIVERY_ENABLED=True,RESEND_API_KEY='synthetic',REPORT_EMAIL_FROM='reports@example.invalid')
    def test_send_action_starts_after_commit_and_reuses_uuid(self):
        schedule=save_configuration(self.user,'tat_tracker',self.payload)
        request={'action':'send','id':str(schedule.pk),'client_request_id':str(uuid.uuid4())}
        with patch('report_delivery.dispatch.Thread') as thread, patch('report_delivery.resend.send_email') as provider:
            with self.captureOnCommitCallbacks(execute=True):
                first=settings_action(self.user,'tat_tracker',request)
                second=settings_action(self.user,'tat_tracker',request)
                thread.assert_not_called()
            self.assertTrue(thread.called)
            self.assertEqual(first['delivery_ids'],second['delivery_ids'])
            # Do not execute a real thread in the transaction test harness.
            from report_delivery.dispatch import _slots
            for _ in thread.call_args_list:
                _slots.release()
        provider.assert_not_called()
        self.assertEqual(schedule.deliveries.count(),1)

    def test_delivery_status_cannot_cross_apps_or_scope(self):
        schedule=save_configuration(self.user,'tat_tracker',self.payload)
        from report_delivery.services import queue_schedule
        delivery=queue_schedule(schedule.pk,actor=self.user,request_key=uuid.uuid4())[0]
        data=settings_action(self.user,'tat_tracker',{'action':'status','delivery_ids':[str(delivery.pk)]})
        self.assertEqual(data['deliveries'][0]['status'],'queued')
        other=get_user_model().objects.create_user(username='synthetic-other-report-it')
        AccessGrant.objects.create(user=other,workflow='complaint_cases',role='IT',group_configuration=self.group)
        with self.assertRaises(ValidationError):
            settings_action(other,'complaint_cases',{'action':'status','delivery_ids':[str(delivery.pk)]})

    def test_tat_adapter_supplies_period_group_and_scope(self):
        schedule=save_configuration(self.user,'tat_tracker',{**self.payload,'branch':'A','product':'X'})
        with patch('core.services.tat_reporting.report_summary',return_value={'metrics':{},'charts':{}}) as summary, patch('core.services.tat_reporting.report_cases',return_value={'results':[],'count':0}):
            snapshot=capture_workflow_report(schedule,{'period':{'from':'2026-09-01','to':'2026-09-30'}})
        payload=summary.call_args.args[1]
        self.assertEqual(payload['view'],'performance')
        self.assertEqual(payload['group'],self.group.group_id)
        self.assertEqual(payload['product'],'X')
        self.assertEqual(snapshot['preset'],'tat')

    def test_complaints_adapter_excludes_other_groups_and_branches(self):
        from core.models import RawMessage, ProcessedMessage, ParsedMessage, ComplaintCaseControl
        from django.utils import timezone
        AccessGrant.objects.create(user=self.user,workflow='complaint_cases',role='IT',group_configuration=self.group)
        schedule=save_configuration(self.user,'complaint_cases',{**self.payload,'preset':'complaints','branch':'A'})
        for index,(group,branch) in enumerate([(self.group.group_id,'A'),(self.group.group_id,'B'),('another-group','A')]):
            raw=RawMessage.objects.create(telegram_message_id=f'synthetic-email-{index}',content='Synthetic')
            processed=ProcessedMessage.objects.create(raw_message=raw,message_hash=f'synthetic-email-{index}')
            case=ParsedMessage.objects.create(processed_message=processed,message_id=f'synthetic-email-{index}',group_id=group,
                customer_name=f'Synthetic {index}',branch_region=branch,timestamp=timezone.now(),raw_message='',complaint_status='Open')
            ComplaintCaseControl.objects.create(parsed_message=case,reference_number=f'CMP-EMAIL-{index}')
        today=timezone.localdate().isoformat()
        snapshot=capture_workflow_report(schedule,{'period':{'from':today,'to':today}})
        self.assertEqual(snapshot['total_rows'],1)
        self.assertEqual(snapshot['summary']['Complaints received'],1)
        self.assertEqual([r['customer_name'] for r in snapshot['rows']],['Synthetic 0'])

    def test_real_tat_adapter_handles_empty_period(self):
        schedule=save_configuration(self.user,'tat_tracker',self.payload)
        snapshot=capture_workflow_report(schedule,{'period':{'from':'2026-09-01','to':'2026-09-30'}})
        self.assertEqual(snapshot['total_rows'],0)
        self.assertEqual(snapshot['rows'],[])

    def test_app_http_boundaries_authenticate_before_own_authorization(self):
        from django.test import RequestFactory
        from types import SimpleNamespace
        from report_delivery.views import tat_report_settings, complaint_report_settings
        request=RequestFactory().post('/api/tat-tracker/settings/reports/',data='{}',content_type='application/json')
        with patch('core.api.views._tat_context',return_value=('',None,{}, {'user_id':self.user.pk},None)):
            self.assertEqual(tat_report_settings(request).status_code,200)
        with patch('core.api.complaint_case_views._context',return_value=(None,SimpleNamespace(user=self.user),None)):
            self.assertEqual(complaint_report_settings(request).status_code,403)
