from unittest.mock import MagicMock, patch
from decimal import Decimal
from io import BytesIO, StringIO
import hashlib
import hmac
import json
import time
from pathlib import Path
from urllib.parse import urlencode

import openpyxl
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.admin import TatTrackerStaffMemberAdminForm
from core.models import GroupSheetConfiguration, TatTrackerApprovalCertificate, TatTrackerCase, TatTrackerEvent, TatTrackerStaffMember
from core.api.views import _dispatch_tat_approval_certificate, _process_telegram_message
from core.services.group_config import GroupRegistry
from core.services.tat_tracker import (
    _TAT_HEADER_CACHE,
    bootstrap,
    build_tat_tracker_url,
    calculated_tat_days,
    calculated_tat_hours,
    calculated_tat_minutes,
    create_tat_start_param,
    decode_tat_start_param,
    get_case_detail,
    product_by_key,
    parse_tat_batch_rows,
    parse_tat_batch_file,
    parse_iso_datetime,
    process_tat_batch_upload,
    process_tat_batch_file,
    previous_stages_complete,
    stage_by_key,
    stage_tat_minutes,
    tat_days_formula,
    can_manage_tat_targets,
    normalize_tat_target_settings,
    update_tat_target_settings,
    tat_hours_formula,
    create_case,
    is_tat_tracker_workflow,
    home_data,
    next_role_alert,
    staff_user_for_payload,
    sync_case_to_sheet,
    sync_tat_batch_created_cases,
    resync_tat_tracker_cases,
    search_cases,
    soft_delete_tat_case,
    sync_tat_target_settings_to_sheet,
    tat_batch_format_message,
    validate_tracker_identity_headers,
    update_case,
    workflow_branches,
)


@override_settings(SECURE_SSL_REDIRECT=False)
class TatTrackerWorkflowTest(TestCase):
    def setUp(self):
        _TAT_HEADER_CACHE.clear()
        GroupRegistry._instance = None
        self.config = GroupSheetConfiguration.objects.create(
            group_id='-100tat',
            display_name='TAT Test',
            sheet_id='sheet123',
            sheet_name='TRACKER-Business',
            workflow={
                'type': 'tat_tracker',
                'products': ['business', 'logbook'],
                'branches': ['Nakuru', 'Embu'],
                'staff': [
                    {
                        'telegram_user_id': '111',
                        'telegram_username': 'bro_user',
                        'name': 'BRO User',
                        'roles': ['BRO'],
                        'branches': ['Nakuru'],
                        'products': ['business'],
                        'active': True,
                    },
                    {
                        'telegram_user_id': '222',
                        'telegram_username': 'admin_user',
                        'name': 'Admin User',
                        'roles': ['ADMIN'],
                        'branches': ['Nakuru'],
                        'products': ['business'],
                        'active': True,
                    },
                ],
            },
        )

    def signed_init_data(self, telegram_id='111', username='bro_user'):
        pairs = {
            'auth_date': str(int(time.time())),
            'user': json.dumps({'id': int(telegram_id), 'username': username}),
        }
        check = '\n'.join(f'{key}={value}' for key, value in sorted(pairs.items()))
        secret = hmac.new(b'WebAppData', b'test-bot-token', hashlib.sha256).digest()
        pairs['hash'] = hmac.new(secret, check.encode('utf-8'), hashlib.sha256).hexdigest()
        return urlencode(pairs)

    def test_detects_tat_tracker_workflow(self):
        self.assertTrue(is_tat_tracker_workflow(self.config))

    def test_product_amount_limits_match_current_tat_policy(self):
        self.assertEqual(product_by_key('logbook').max_amount, Decimal('700000'))
        self.assertEqual(product_by_key('mjengo').min_amount, Decimal('10000'))
        self.assertEqual(product_by_key('mjengo').max_amount, Decimal('500000'))
        self.assertEqual(product_by_key('micro_asset').min_amount, Decimal('10000'))

    def test_home_lists_paginate_independently(self):
        for index in range(12):
            TatTrackerCase.objects.create(
                group_id=self.config.group_id,
                case_id=f'JBL-BS-2026-{index:03d}',
                product_key='business',
                product_label='Business',
                client_name=f'Client {index}',
                branch='Nakuru',
                status='Active',
                stage_values={'created': timezone.now().isoformat()},
            )
        user = staff_user_for_payload(self.config, {'id': 111, 'username': 'bro_user'})

        first_page = home_data(self.config, user)
        second_page = home_data(self.config, user, action_offset=10, recent_offset=10)

        self.assertEqual(len(first_page['action_required']), 10)
        self.assertEqual(first_page['pagination']['action_required']['total'], 12)
        self.assertTrue(first_page['pagination']['action_required']['has_more'])
        self.assertEqual(len(second_page['action_required']), 2)
        self.assertFalse(second_page['pagination']['action_required']['has_more'])
        self.assertEqual(len(first_page['recent']), 10)
        self.assertEqual(len(second_page['recent']), 2)

    @override_settings(TELEGRAM_BOT_TOKEN='test-bot-token')
    def test_home_fragment_renders_recent_cases(self):
        TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            case_id='JBL-BS-2026-001',
            product_key='business',
            product_label='Business',
            client_name='Fragment Client',
            branch='Nakuru',
            status='Active',
            stage_values={'created': timezone.now().isoformat()},
        )

        response = self.client.post(
            reverse('tat_tracker_home_fragment'),
            {
                'group_id': self.config.group_id,
                'init_data': self.signed_init_data(),
                'list': 'recent',
                'product_key': 'business',
                'branch': 'Nakuru',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'tat_tracker/partials/case_list.html')
        self.assertContains(response, 'Fragment Client')
        self.assertContains(response, 'htmx-tat-case-card')

    @override_settings(TELEGRAM_BOT_TOKEN='test-bot-token')
    def test_search_fragment_renders_matching_cases(self):
        TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            case_id='JBL-BS-2026-002',
            product_key='business',
            product_label='Business',
            client_name='Searchable Client',
            national_id='12345678',
            primary_phone='254712345678',
            branch='Nakuru',
            status='Active',
            stage_values={'created': timezone.now().isoformat()},
        )

        response = self.client.post(
            reverse('tat_tracker_search_fragment'),
            {
                'group_id': self.config.group_id,
                'init_data': self.signed_init_data(),
                'query': 'Searchable',
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Searchable Client')
        self.assertContains(response, 'JBL-BS-2026-002')

    def test_home_data_filters_by_product_and_branch(self):
        cases = [
            ('JBL-BS-2026-001', 'business', 'Business', 'Nakuru', 'Business Nakuru'),
            ('JBL-BS-2026-002', 'business', 'Business', 'Embu', 'Business Embu'),
            ('JBL-LB-2026-001', 'logbook', 'Logbook', 'Nakuru', 'Logbook Nakuru'),
        ]
        for case_id, product_key, product_label, branch, client_name in cases:
            TatTrackerCase.objects.create(
                group_id=self.config.group_id,
                case_id=case_id,
                product_key=product_key,
                product_label=product_label,
                client_name=client_name,
                branch=branch,
                status='Active',
                stage_values={'created': timezone.now().isoformat()},
            )
        user = {
            'name': 'IT User',
            'roles': ['IT'],
            'branches': ['Nakuru', 'Embu'],
            'products': ['business', 'logbook'],
        }

        filtered = home_data(self.config, user, product_key='business', branch='Nakuru')

        self.assertEqual(filtered['pagination']['recent']['total'], 1)
        self.assertEqual(filtered['recent'][0]['case_id'], 'JBL-BS-2026-001')
        self.assertTrue(all(item['product_key'] == 'business' for item in filtered['recent']))
        self.assertTrue(all(item['branch'] == 'Nakuru' for item in filtered['recent']))

    def test_soft_deleted_cases_are_hidden_from_mini_app_lists(self):
        deleted_case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            case_id='JBL-BS-2026-DEL',
            product_key='business',
            product_label='Business',
            client_name='Deleted Client',
            branch='Nakuru',
            status='Active',
            stage_values={'created': timezone.now().isoformat()},
        )
        active_case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            case_id='JBL-BS-2026-ACT',
            product_key='business',
            product_label='Business',
            client_name='Active Client',
            branch='Nakuru',
            status='Active',
            stage_values={'created': timezone.now().isoformat()},
        )
        user = staff_user_for_payload(self.config, {'id': 111, 'username': 'bro_user'})

        changed = soft_delete_tat_case(
            deleted_case,
            actor_name='Admin User',
            actor_role='ADMIN',
            reason='Duplicate test data cleanup.',
        )

        self.assertTrue(changed)
        deleted_case.refresh_from_db()
        self.assertTrue(deleted_case.is_deleted)
        self.assertEqual(deleted_case.deleted_by, 'Admin User')
        self.assertEqual(
            TatTrackerEvent.objects.filter(case=deleted_case, stage_key='deleted').count(),
            1,
        )

        home = home_data(self.config, user)
        home_ids = {item['case_id'] for item in home['recent']}
        self.assertNotIn(deleted_case.case_id, home_ids)
        self.assertIn(active_case.case_id, home_ids)

        search_results = search_cases(self.config, user, 'Deleted')
        self.assertEqual(search_results, [])
        with self.assertRaises(TatTrackerCase.DoesNotExist):
            get_case_detail(self.config, user, deleted_case.case_id)

    def test_tat_mini_app_sends_queue_filters_with_home_pagination(self):
        source = Path('core/static/miniapp/tat_tracker.js').read_text(encoding='utf-8')
        template = Path('core/templates/tat_tracker/app.html').read_text(encoding='utf-8')

        self.assertIn('id="queueProductFilter"', template)
        self.assertIn('id="queueBranchFilter"', template)
        self.assertIn("miniapp/utils.js", template)
        self.assertIn("product_key: $('queueProductFilter') ? $('queueProductFilter').value : ''", source)
        self.assertIn("branch: $('queueBranchFilter') ? $('queueBranchFilter').value : ''", source)
        self.assertIn("api('/api/tat-tracker/home/', homePayload(payload))", source)
        self.assertIn('utils.fetchJson(path', source)

    @patch('core.services.tat_tracker.sync_tat_target_settings_to_sheet', return_value={'status': 'unavailable'})
    def test_it_can_save_stage_targets_in_minutes(self, sync_targets):
        user = {'roles': ['IT'], 'name': 'IT User'}

        result = update_tat_target_settings(self.config, user, {
            'business': {
                'total_minutes': '1440',
                'stages': {'mpesa_to_admin': '30'},
            },
            'logbook': {'total_minutes': '', 'stages': {}},
        })

        self.config.refresh_from_db()
        targets = self.config.workflow['tat_targets_minutes']['business']
        self.assertTrue(result['changed'])
        self.assertEqual(targets['total'], 1440)
        self.assertEqual(targets['stages']['mpesa_to_admin'], 30)
        sync_targets.assert_called_once()

    def test_admin_cannot_save_tat_targets(self):
        user = staff_user_for_payload(self.config, {'id': 222, 'username': 'admin_user'})

        self.assertFalse(can_manage_tat_targets(user))
        with self.assertRaisesRegex(ValueError, 'Only IT'):
            update_tat_target_settings(self.config, user, {})

    def test_target_minutes_must_be_whole_number(self):
        with self.assertRaisesRegex(ValueError, 'whole minutes'):
            normalize_tat_target_settings(self.config.workflow, {
                'business': {'total_minutes': '0.01', 'stages': {}},
                'logbook': {'total_minutes': '', 'stages': {}},
            })

    @patch('core.services.tat_tracker.get_sheets_service')
    def test_target_sync_creates_missing_support_tab(self, get_service):
        sheet = MagicMock()
        get_service.return_value.get_or_create_worksheet.return_value = sheet

        result = sync_tat_target_settings_to_sheet(self.config, {
            'products': ['business'],
            'tat_targets_minutes': {'business': {'total': 1440, 'stages': {'mpesa_to_admin': 30}}},
        })

        self.assertEqual(result['status'], 'synced')
        get_service.return_value.get_or_create_worksheet.assert_called_once_with('TAT TARGETS', rows=500, cols=4)
        sheet.batch_clear.assert_called_once_with(['A2:D500'])

    @override_settings(TAT_TRACKER_SIGNATURES_ENABLED=True)
    def test_sme_bm_certificate_blocks_the_next_stage_until_signed(self):
        staff_member = TatTrackerStaffMember.objects.create(
            group_configuration=self.config,
            name='BM User',
            telegram_user_id='333',
            roles='BM',
            branches='Nakuru',
            products='business',
            signing_national_id='12345678',
            signing_phone_number='+254700000001',
        )
        case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-Business',
            case_id='JBL-BS-2026-APPROVAL',
            product_key='business',
            product_label='Business',
            client_name='Approval Client',
            branch='Nakuru',
            bro_name='BRO User',
            amount='10000',
            stage_values={
                'created': timezone.now().isoformat(),
                'mpesa_to_admin': timezone.now().isoformat(),
                'mpesa_verified': timezone.now().isoformat(),
                'ca_analysis_sent': timezone.now().isoformat(),
                'bro_response': timezone.now().isoformat(),
                'bm_response': timezone.now().isoformat(),
            },
        )
        event = TatTrackerEvent.objects.create(case=case, group_id=case.group_id, stage_key='bm_response')
        certificate = TatTrackerApprovalCertificate.objects.create(
            case=case,
            event=event,
            staff_member=staff_member,
            stage_key='bm_response',
            external_reference='TAT-test-bm-response-v1',
        )
        next_stage = stage_by_key(product_by_key('business'), 'bro_applied')

        self.assertFalse(previous_stages_complete(case, next_stage))

        certificate.status = 'signed'
        certificate.save(update_fields=['status'])

        self.assertTrue(previous_stages_complete(case, next_stage))

    @override_settings(TAT_TRACKER_SIGNATURES_ENABLED=False)
    @patch('core.models.TatTrackerApprovalCertificate.objects.filter')
    def test_signature_dispatch_is_disabled_by_default(self, certificate_filter):
        _dispatch_tat_approval_certificate('JBL-BS-2026-001', {'telegram_id': '333'})

        certificate_filter.assert_not_called()
    def test_sme_bm_certificate_does_not_block_when_signatures_are_disabled(self):
        case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-Business',
            case_id='JBL-BS-2026-SIGNATURES-OFF',
            product_key='business',
            product_label='Business',
            client_name='Approval Client',
            branch='Nakuru',
            bro_name='BRO User',
            amount='10000',
            stage_values={
                'created': timezone.now().isoformat(),
                'mpesa_to_admin': timezone.now().isoformat(),
                'mpesa_verified': timezone.now().isoformat(),
                'ca_analysis_sent': timezone.now().isoformat(),
                'bro_response': timezone.now().isoformat(),
                'bm_response': timezone.now().isoformat(),
            },
        )

        self.assertTrue(previous_stages_complete(case, stage_by_key(product_by_key('business'), 'bro_applied')))
    @override_settings(APP_BASE_URL='https://example.test')
    def test_builds_secure_tracker_url(self):
        url = build_tat_tracker_url(self.config.group_id)
        self.assertIn('https://example.test/tat-tracker/', url)
        self.assertIn('group_id=-100tat', url)
        self.assertIn('token=', url)


    @override_settings(APP_BASE_URL='https://example.test', TELEGRAM_BOT_USERNAME='testbot', TAT_TRACKER_MINI_APP_SHORT_NAME='tattracker')
    def test_tat_command_routes_to_mini_app_button(self):
        GroupRegistry._instance = None
        result = _process_telegram_message({
            'message_id': 900,
            'chat': {'id': self.config.group_id, 'type': 'supergroup', 'title': 'TAT Test'},
            'from': {'id': 111, 'first_name': 'BRO', 'last_name': 'User', 'username': 'bro_user'},
            'text': '@testbot /tat',
            'date': 1783920000,
        })

        self.assertEqual(result['status'], 'command')
        self.assertIn('TAT Tracker', result['reply_text'])
        button = result['reply_markup']['inline_keyboard'][0][0]
        self.assertEqual(button['text'], 'Open TAT Tracker Mini App')
        self.assertIn('url', button)
        self.assertNotIn('web_app', button)
        self.assertTrue(button['url'].startswith('https://t.me/testbot/tattracker?startapp='))

    @override_settings(TELEGRAM_BOT_USERNAME='testbot')
    def test_tatbatch_command_returns_batch_format(self):
        GroupRegistry._instance = None
        result = _process_telegram_message({
            'message_id': 901,
            'chat': {'id': self.config.group_id, 'type': 'supergroup', 'title': 'TAT Test'},
            'from': {'id': 111, 'first_name': 'BRO', 'last_name': 'User', 'username': 'bro_user'},
            'text': '@testbot /tatbatch',
            'date': 1783920000,
        })

        self.assertEqual(result['status'], 'command')
        self.assertIn('Attach an Excel .xlsx or CSV file', result['reply_text'])
        self.assertIn('Product, Client Name, National ID, Phone, Branch, Amount', result['reply_text'])

    def test_parse_tat_batch_rows_accepts_pipe_rows(self):
        rows = parse_tat_batch_rows(
            "product | client name | national id | phone | branch | amount\n"
            "business | Mary Wanjiku | 12345678 | 254712345678 | Nakuru | 25000"
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['payload']['product_key'], 'business')
        self.assertEqual(rows[0]['payload']['client_name'], 'Mary Wanjiku')

    def test_parse_tat_batch_csv_accepts_required_headers(self):
        rows = parse_tat_batch_file(
            'tat_batch.csv',
            (
                "Product,Client Name,National ID,Phone,Branch,Amount\n"
                "business,Mary Wanjiku,12345678,254712345678,Nakuru,25000\n"
            ).encode('utf-8'),
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['line_number'], 2)
        self.assertEqual(rows[0]['payload']['product_key'], 'business')
        self.assertEqual(rows[0]['payload']['primary_phone'], '254712345678')

    def test_parse_tat_batch_xlsx_accepts_required_headers(self):
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.append(['Product', 'Client Name', 'National ID', 'Phone', 'Branch', 'Amount'])
        sheet.append(['business', 'Mary Wanjiku', '12345678', '254712345678', 'Nakuru', '25000'])
        stream = BytesIO()
        workbook.save(stream)

        rows = parse_tat_batch_file('tat_batch.xlsx', stream.getvalue())

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['line_number'], 2)
        self.assertEqual(rows[0]['payload']['client_name'], 'Mary Wanjiku')

    @patch('core.services.tat_tracker.sync_tat_batch_created_cases', return_value={'synced': 1, 'failed': []})
    def test_bro_can_upload_tat_batch_csv_file(self, sync_mock):
        result = process_tat_batch_file(
            self.config,
            filename='tat_batch.csv',
            content=(
                "Product,Client Name,National ID,Phone,Branch,Amount\n"
                "business,Mary Wanjiku,12345678,254712345678,Nakuru,25000\n"
            ).encode('utf-8'),
            user_payload={'id': 111, 'username': 'bro_user'},
            telegram_message_id='csv-1',
            sender='BRO User',
        )

        self.assertEqual(result['status'], 'tat_batch_processed')
        self.assertEqual(result['created'], 1)
        self.assertEqual(TatTrackerCase.objects.get().client_name, 'MARY WANJIKU')
        sync_mock.assert_called_once()

    @override_settings(TELEGRAM_BOT_USERNAME='testbot')
    @patch('core.services.tat_tracker.sync_tat_batch_created_cases', return_value={'synced': 1, 'failed': []})
    def test_bro_can_upload_tat_batch_with_batch_command(self, sync_mock):
        GroupRegistry._instance = None
        result = _process_telegram_message({
            'message_id': 902,
            'chat': {'id': self.config.group_id, 'type': 'supergroup', 'title': 'TAT Test'},
            'from': {'id': 111, 'first_name': 'BRO', 'last_name': 'User', 'username': 'bro_user'},
            'text': (
                '@testbot /batch\n'
                'business | Mary Wanjiku | 12345678 | 254712345678 | Nakuru | 25000'
            ),
            'date': 1783920000,
        })

        self.assertEqual(result['status'], 'tat_batch_processed')
        self.assertEqual(result['created'], 1)
        case = TatTrackerCase.objects.get(client_name='MARY WANJIKU')
        self.assertEqual(case.bro_name, 'BRO User')
        self.assertEqual(case.create_request_id, 'tat-batch:-100tat:902:1')
        sync_mock.assert_called_once()

    @patch('core.services.tat_tracker.sync_tat_batch_created_cases', return_value={'synced': 1, 'failed': []})
    def test_tat_batch_retry_is_idempotent(self, sync_mock):
        payload = (
            "business | Mary Wanjiku | 12345678 | 254712345678 | Nakuru | 25000"
        )

        first = process_tat_batch_upload(
            self.config,
            payload,
            user_payload={'id': 111, 'username': 'bro_user'},
            telegram_message_id='retry-1',
            sender='BRO User',
        )
        second = process_tat_batch_upload(
            self.config,
            payload,
            user_payload={'id': 111, 'username': 'bro_user'},
            telegram_message_id='retry-1',
            sender='BRO User',
        )

        self.assertEqual(first['created'], 1)
        self.assertEqual(second['duplicates'], 1)
        self.assertEqual(TatTrackerCase.objects.filter(client_name='MARY WANJIKU').count(), 1)

    def test_non_bro_cannot_upload_tat_batch(self):
        result = process_tat_batch_upload(
            self.config,
            "business | Mary Wanjiku | 12345678 | 254712345678 | Nakuru | 25000",
            user_payload={'id': 222, 'username': 'admin_user'},
            telegram_message_id='not-bro',
            sender='Admin User',
        )

        self.assertEqual(result['status'], 'command')
        self.assertIn('Only configured BRO users', result['reply_text'])

    @override_settings(STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    })
    def test_tat_app_preserves_signed_token_from_start_param(self):
        start_param = create_tat_start_param(self.config.group_id)
        token = decode_tat_start_param(start_param)['token']

        response = self.client.get('/tat-tracker/', {'tgWebAppStartParam': start_param})

        self.assertEqual(response.status_code, 200)
        html = response.content.decode('utf-8')
        self.assertIn(f'data-token="{token}"', html)
        self.assertNotIn('\\u003A', html)



    def test_workflow_branches_replace_stale_default_branch_list(self):
        stale_workflow = {
            'branches': ['Corporate', 'Thika Road', 'East Nairobi', 'West Nairobi', 'Nakuru', 'Embu', 'Limuru'],
        }

        self.assertEqual(workflow_branches(stale_workflow), ['Biogas Unit', 'Embu', 'Nakuru', 'West Nairobi'])

    @override_settings(TAT_TRACKER_BRANCH_CHOICES='Biogas Unit, Muranga, Thika Road')
    def test_workflow_branches_use_tat_env_override(self):
        workflow = {
            'branches': ['Nakuru', 'Embu'],
        }

        self.assertEqual(workflow_branches(workflow), ['Biogas Unit', 'Muranga', 'Thika Road'])

    @override_settings(TAT_TRACKER_BRANCH_CHOICES='Biogas Unit,Nakuru,Muranga')
    def test_bootstrap_filters_tat_env_branches_by_staff_access(self):
        data = bootstrap(self.config, {'id': 111, 'username': 'bro_user'})

        self.assertEqual(data['branches'], ['Nakuru'])
        self.assertEqual(data['bro_names'], ['BRO User'])
        self.assertEqual(data['bro_names'], ['BRO User'])

    def test_tat_formula_helpers_match_tracker_columns(self):
        business = product_by_key('business')
        logbook = product_by_key('logbook')
        mjengo = product_by_key('mjengo')

        self.assertEqual(tat_hours_formula(business, 5), '=IF(OR($H5="",$R5=""),"",ROUND(($R5-$H5)*24,2))')
        self.assertEqual(tat_days_formula(business, 5), '=IF(U5="","",ROUND(U5/24,2))')
        self.assertEqual(tat_hours_formula(logbook, 5), '=IF(OR($H5="",$Z5=""),"",ROUND(($Z5-$H5)*24,2))')
        self.assertEqual(tat_days_formula(logbook, 5), '=IF(AC5="","",ROUND(AC5/24,2))')
        self.assertEqual(tat_hours_formula(mjengo, 5), '=IF(OR($H5="",$Y5=""),"",ROUND(($Y5-$H5)*24,2))')
        self.assertEqual(tat_days_formula(mjengo, 5), '=IF(AB5="","",ROUND(AB5/24,2))')
    def test_group_config_merges_gui_staff_rows_into_workflow(self):
        TatTrackerStaffMember.objects.create(
            group_configuration=self.config,
            name='GUI Staff',
            telegram_user_id='333',
            telegram_username='gui_staff',
            roles='CA,BM',
            branches='ALL',
            products='business,logbook',
        )
        TatTrackerStaffMember.objects.create(
            group_configuration=self.config,
            name='Inactive Staff',
            telegram_user_id='444',
            roles='BRO',
            active=False,
        )

        workflow = self.config.as_group_config_kwargs()['workflow']
        self.assertEqual(len(workflow['staff']), 1)
        self.assertEqual(workflow['staff'][0]['name'], 'GUI Staff')
        self.assertEqual(workflow['staff'][0]['roles'], ['CA', 'BM'])
        self.assertEqual(workflow['staff'][0]['branches'], ['ALL'])
        self.assertEqual(workflow['staff'][0]['products'], ['business', 'logbook'])


    def test_gui_staff_rows_override_legacy_workflow_staff_even_when_inactive(self):
        self.config.workflow['staff'] = [{
            'telegram_user_id': '999',
            'name': 'Legacy JSON Staff',
            'roles': ['IT'],
            'branches': ['ALL'],
            'products': ['ALL'],
            'active': True,
        }]
        self.config.save()
        TatTrackerStaffMember.objects.create(
            group_configuration=self.config,
            name='Disabled GUI Staff',
            telegram_user_id='555',
            roles='BRO',
            active=False,
        )

        workflow = self.config.as_group_config_kwargs()['workflow']

        self.assertEqual(workflow['staff'], [])

    def test_staff_admin_form_renders_saved_checkbox_values(self):
        staff = TatTrackerStaffMember.objects.create(
            group_configuration=self.config,
            name='GUI Staff',
            telegram_user_id='333',
            roles='CA,BM',
            branches='Nakuru,Embu',
            products='business,logbook',
        )

        form = TatTrackerStaffMemberAdminForm(instance=staff)

        self.assertEqual(form['roles'].value(), ['CA', 'BM'])
        self.assertEqual(form['branches'].value(), ['Nakuru', 'Embu'])
        self.assertEqual(form['products'].value(), ['business', 'logbook'])
        html = form.as_p()
        self.assertIn('name="roles" value="CA"', html)
        self.assertIn('name="roles" value="BM"', html)
        self.assertIn('value="CA" id="id_roles_2" checked', html)
        self.assertIn('value="BM" id="id_roles_3" checked', html)

    def test_staff_admin_form_saves_checkbox_values_as_csv(self):
        data = {
            'group_configuration': str(self.config.pk),
            'name': 'GUI Staff',
            'telegram_user_id': '333',
            'telegram_username': '',
            'roles': ['CA', 'BM'],
            'branches': ['Nakuru', 'Embu'],
            'products': ['business', 'logbook'],
            'active': 'on',
            'notes': '',
        }

        form = TatTrackerStaffMemberAdminForm(data=data)

        self.assertTrue(form.is_valid(), form.errors)
        staff = form.save()
        self.assertEqual(staff.roles, 'CA,BM')
        self.assertEqual(staff.branches, 'Nakuru,Embu')
        self.assertEqual(staff.products, 'business,logbook')

    def test_staff_admin_form_limits_branches_to_the_group_configuration(self):
        self.config.workflow['branches'] = ['Muranga', 'Thika Road']
        self.config.save(update_fields=['workflow'])
        data = {
            'group_configuration': str(self.config.pk),
            'name': 'Configured Branch Staff',
            'telegram_user_id': '334',
            'roles': ['BRO'],
            'branches': ['Nakuru'],
            'products': ['business'],
            'active': 'on',
        }

        form = TatTrackerStaffMemberAdminForm(data=data)

        self.assertEqual(
            list(form.fields['branches'].choices),
            [('ALL', 'All branches'), ('Muranga', 'Muranga'), ('Thika Road', 'Thika Road')],
        )
        self.assertFalse(form.is_valid())

    def test_group_admin_form_exposes_tat_targets_from_workflow(self):
        self.config.workflow.setdefault('tat_targets_minutes', {}).setdefault(
            'business',
            {'total': 20160, 'stages': {}},
        )['stages'] = {
            'mpesa_to_admin': 45,
            'ca_analysis_sent': 180,
        }
        self.config.save()

        from core.admin import GroupSheetConfigurationAdminForm

        form = GroupSheetConfigurationAdminForm(instance=self.config)

        self.assertIn('tat_target_business_total', form.fields)
        self.assertIn('tat_target_business_mpesa_to_admin', form.fields)
        self.assertEqual(form['tat_target_business_total'].value(), 20160)
        self.assertEqual(form['tat_target_business_mpesa_to_admin'].value(), 45)
        self.assertEqual(form['tat_target_business_ca_analysis_sent'].value(), 180)

    def test_group_admin_form_saves_tat_targets_into_generated_workflow(self):
        from core.admin import GroupSheetConfigurationAdminForm

        data = {
            'workflow_preset': 'tat_tracker',
            'group_id': self.config.group_id,
            'display_name': self.config.display_name,
            'enabled': 'on',
            'sheet_id': self.config.sheet_id,
            'sheet_name': self.config.sheet_name,
            'sheet_schema': '{}',
            'workflow': json.dumps(self.config.workflow),
            'parser_rules': '{}',
            'metadata': '{}',
            'tat_target_business_total': '1440',
            'tat_target_business_mpesa_to_admin': '30',
            'tat_target_business_ca_analysis_sent': '120',
        }

        form = GroupSheetConfigurationAdminForm(data=data, instance=self.config)

        self.assertTrue(form.is_valid(), form.errors)
        workflow = form.generated_workflow()
        self.assertEqual(workflow['tat_targets_minutes']['business']['total'], 1440)
        self.assertEqual(
            workflow['tat_targets_minutes']['business']['stages']['mpesa_to_admin'],
            30,
        )
        self.assertEqual(
            workflow['tat_targets_minutes']['business']['stages']['ca_analysis_sent'],
            120,
        )

    def test_group_admin_form_preserves_existing_tat_targets_when_fields_blank(self):
        self.config.workflow.setdefault('tat_targets_minutes', {}).setdefault(
            'business',
            {'total': 20160, 'stages': {}},
        )['stages'] = {
            'mpesa_to_admin': 45,
            'ca_analysis_sent': 180,
        }
        self.config.save()

        from core.admin import GroupSheetConfigurationAdminForm

        data = {
            'workflow_preset': 'tat_tracker',
            'group_id': self.config.group_id,
            'display_name': self.config.display_name,
            'enabled': 'on',
            'sheet_id': self.config.sheet_id,
            'sheet_name': self.config.sheet_name,
            'sheet_schema': '{}',
            'workflow': json.dumps(self.config.workflow),
            'parser_rules': '{}',
            'metadata': '{}',
        }

        form = GroupSheetConfigurationAdminForm(data=data, instance=self.config)

        self.assertTrue(form.is_valid(), form.errors)
        workflow = form.generated_workflow()
        self.assertEqual(
            workflow['tat_targets_minutes']['business']['stages']['mpesa_to_admin'],
            45,
        )
        self.assertEqual(
            workflow['tat_targets_minutes']['business']['stages']['ca_analysis_sent'],
            180,
        )

    def test_group_admin_form_preserves_existing_tat_workflow_settings(self):
        self.config.workflow.update({
            'products': ['business'],
            'branches': ['Muranga', 'Thika Road'],
            'alert_next_role': False,
        })
        self.config.save()

        from core.admin import GroupSheetConfigurationAdminForm

        data = {
            'workflow_preset': 'tat_tracker',
            'group_id': self.config.group_id,
            'display_name': self.config.display_name,
            'enabled': 'on',
            'sheet_id': self.config.sheet_id,
            'sheet_name': self.config.sheet_name,
            'sheet_schema': '{}',
            'workflow': json.dumps(self.config.workflow),
            'parser_rules': '{}',
            'metadata': '{}',
            'tat_target_business_total': '1440',
        }

        form = GroupSheetConfigurationAdminForm(data=data, instance=self.config)

        self.assertTrue(form.is_valid(), form.errors)
        workflow = form.generated_workflow()
        self.assertEqual(workflow['products'], ['business'])
        self.assertEqual(workflow['branches'], ['Muranga', 'Thika Road'])
        self.assertIs(workflow['alert_next_role'], False)
        self.assertEqual(workflow['tat_targets_minutes']['business']['total'], 1440)

    def test_group_admin_form_loads_tat_targets_even_when_preset_is_manual(self):
        self.config.workflow = {
            'type': 'custom_tat_tracker',
            'tat_targets_minutes': {
                'business': {
                    'total': 1440,
                    'stages': {'mpesa_to_admin': 30},
                },
            },
        }
        self.config.save()

        from core.admin import GroupSheetConfigurationAdminForm

        form = GroupSheetConfigurationAdminForm(instance=self.config)

        self.assertEqual(form['tat_target_business_total'].value(), 1440)
        self.assertEqual(form['tat_target_business_mpesa_to_admin'].value(), 30)

    def test_group_admin_manual_tat_workflow_merges_gui_target_fields(self):
        self.config.workflow = {
            'type': 'tat_tracker',
            'products': ['business'],
            'branches': ['Nakuru'],
            'tat_targets_minutes': {
                'business': {
                    'total': 20160,
                    'stages': {'mpesa_to_admin': 45},
                },
            },
        }
        self.config.save()

        from core.admin import GroupSheetConfigurationAdminForm

        data = {
            'workflow_preset': 'manual',
            'group_id': self.config.group_id,
            'display_name': self.config.display_name,
            'enabled': 'on',
            'sheet_id': self.config.sheet_id,
            'sheet_name': self.config.sheet_name,
            'sheet_schema': '{}',
            'workflow': json.dumps(self.config.workflow),
            'parser_rules': '{}',
            'metadata': '{}',
            'tat_target_business_total': '1440',
            'tat_target_business_ca_analysis_sent': '120',
        }

        form = GroupSheetConfigurationAdminForm(data=data, instance=self.config)

        self.assertTrue(form.is_valid(), form.errors)
        workflow = form.generated_workflow()
        self.assertEqual(workflow['products'], ['business'])
        self.assertEqual(workflow['branches'], ['Nakuru'])
        self.assertEqual(workflow['tat_targets_minutes']['business']['total'], 1440)
        self.assertEqual(
            workflow['tat_targets_minutes']['business']['stages']['mpesa_to_admin'],
            45,
        )
        self.assertEqual(
            workflow['tat_targets_minutes']['business']['stages']['ca_analysis_sent'],
            120,
        )

    def test_group_admin_change_form_accepts_tat_target_fieldset_fields(self):
        request = RequestFactory().get('/admin/core/groupsheetconfiguration/2/change/')
        request.user = get_user_model().objects.create_superuser(
            username='admin',
            email='admin@example.test',
            password='password',
        )

        model_admin = admin.site._registry[GroupSheetConfiguration]
        form_class = model_admin.get_form(request, self.config)

        self.assertIn('tat_target_business_total', form_class.base_fields)
        self.assertIn('tat_target_logbook_ca_analysis_sent', form_class.base_fields)
    def test_staff_user_matches_gui_staff_row(self):
        TatTrackerStaffMember.objects.create(
            group_configuration=self.config,
            name='GUI Staff',
            telegram_user_id='333',
            telegram_username='gui_staff',
            roles='CA',
            branches='ALL',
            products='ALL',
        )
        group_config = type('GroupConfigLike', (), self.config.as_group_config_kwargs())()

        user = staff_user_for_payload(group_config, {'id': 333, 'username': 'gui_staff'})

        self.assertTrue(user['authorized'])
        self.assertEqual(user['name'], 'GUI Staff')
        self.assertEqual(user['roles'], ['CA'])
        self.assertEqual(user['branches'], ['ALL'])
        self.assertEqual(user['products'], ['ALL'])
    def test_staff_user_matches_telegram_id(self):
        user = staff_user_for_payload(self.config, {'id': 111, 'username': 'someone_else'})
        self.assertTrue(user['authorized'])
        self.assertEqual(user['name'], 'BRO User')
        self.assertEqual(user['roles'], ['BRO'])

    @staticmethod
    def mark_case_synced(_group_config, case):
        case.row_number = case.row_number or 5
        case.sheet_name = case.sheet_name or 'TRACKER-Business'
        case.sync_error = ''
        case.save(update_fields=['row_number', 'sheet_name', 'sync_error', 'updated_at'])

    @override_settings(TAT_TRACKER_SYNC_SECONDARY_SHEETS=True)
    def test_sync_case_to_sheet_writes_django_calculated_tat_values(self):
        class FakeSheet:
            def __init__(self):
                self.updates = []

            def row_values(self, _row):
                return [''] * 20

            def update(self, a1_range, values, value_input_option=None):
                self.updates.append((a1_range, values, value_input_option))

        class FakeService:
            def __init__(self, sheet):
                self._sheet = sheet

            def is_available(self):
                return True

        sheet = FakeSheet()
        case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-Business',
            row_number=5,
            case_id='JBL-BS-2026-001',
            product_key='business',
            product_label='Business',
            client_name='Test Client',
            national_id='12345678',
            primary_phone='254712345678',
            branch='Nakuru',
            bro_name='BRO User',
            amount='10000',
            stage_values={
                'created': timezone.make_aware(timezone.datetime(2026, 7, 14, 8, 0)).isoformat(),
                'disbursement': timezone.make_aware(timezone.datetime(2026, 7, 15, 14, 0)).isoformat(),
            },
            status='Active',
        )

        with patch('core.services.tat_tracker.get_sheets_service', return_value=FakeService(sheet)), \
             patch('core.services.tat_tracker.sync_case_index'), \
             patch('core.services.tat_tracker.sync_audit_log'):
            sync_case_to_sheet(self.config, case)

        self.assertEqual(sheet.updates[0][0], 'A5:AE5')
        self.assertEqual(len(sheet.updates[0][1][0]), 31)
        self.assertEqual(sheet.updates[0][1][0][2], '12345678')
        self.assertEqual(sheet.updates[0][1][0][3], '254712345678')
        self.assertEqual(sheet.updates[0][1][0][20], 30.0)
        self.assertEqual(sheet.updates[0][1][0][21], 1.25)
        self.assertFalse(any(str(value).startswith('=IF(') for value in sheet.updates[0][1][0]))

    def test_sync_case_to_sheet_keeps_register_approval_tat_numeric(self):
        class FakeSheet:
            def __init__(self):
                self.updates = []

            def row_values(self, row):
                if row == 2:
                    return [''] * 31
                values = [''] * 31
                values[29] = 'legacy TAT value'
                return values

            def update(self, a1_range, values, value_input_option=None):
                self.updates.append((a1_range, values, value_input_option))

        class FakeService:
            def __init__(self, sheet):
                self._sheet = sheet

            def is_available(self):
                return True

        registered_at = timezone.make_aware(timezone.datetime(2026, 7, 15, 9, 0))
        approved_at = timezone.make_aware(timezone.datetime(2026, 7, 15, 10, 0))
        sheet = FakeSheet()
        case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-Business',
            row_number=5,
            case_id='JBL-BS-2026-REGISTER-TAT',
            product_key='business',
            product_label='Business',
            client_name='Approval Client',
            national_id='12345678',
            primary_phone='254712345678',
            branch='Nakuru',
            bro_name='BRO User',
            amount='10000',
            stage_values={
                'created': registered_at.isoformat(),
                'disbursement_register': '10:00am',
                'register_ts': registered_at.isoformat(),
                'register_approved': 'Approved',
            },
            status='Active',
        )
        event = TatTrackerEvent.objects.create(
            case=case,
            group_id=case.group_id,
            actor_name='Loan Approver',
            stage_key='register_approved',
            stage_label='Register approved',
            old_value='',
            new_value='Approved',
            source='mini_app',
        )
        TatTrackerEvent.objects.filter(pk=event.pk).update(created_at=approved_at)

        with patch('core.services.tat_tracker.get_sheets_service', return_value=FakeService(sheet)):
            sync_case_to_sheet(self.config, case)

        self.assertEqual(sheet.updates[0][1][0][29], 60.0)
        event.refresh_from_db()
        self.assertTrue(event.synced_to_sheet)
        self.assertIsNotNone(event.synced_at)
        self.assertEqual(event.sheet_name, 'TRACKER-Business')
        self.assertEqual(event.row_number, 5)
        self.assertEqual(event.sync_error, '')

    def test_primary_sheet_failure_keeps_event_unsynced_with_error(self):
        class UnavailableService:
            def is_available(self):
                return False

        case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-Business',
            case_id='JBL-BS-2026-SYNC-FAIL',
            product_key='business',
            product_label='Business',
            client_name='Sync Failure Client',
            national_id='12345678',
            primary_phone='254712345678',
            branch='Nakuru',
            bro_name='BRO User',
            amount='10000',
            stage_values={'created': timezone.now().isoformat()},
            status='Active',
        )
        event = TatTrackerEvent.objects.create(
            case=case,
            group_id=case.group_id,
            stage_key='created',
            stage_label='Case Created',
            new_value='Created',
        )

        with patch('core.services.tat_tracker.get_sheets_service', return_value=UnavailableService()):
            with self.assertRaisesRegex(RuntimeError, 'Google Sheets service unavailable'):
                sync_case_to_sheet(self.config, case)

        event.refresh_from_db()
        self.assertFalse(event.synced_to_sheet)
        self.assertIsNone(event.synced_at)
        self.assertEqual(event.sync_error, 'Google Sheets service unavailable.')

    def test_sync_case_to_sheet_writes_mjengo_dropdown_values_not_stage_timestamps(self):
        class FakeSheet:
            def __init__(self):
                self.updates = []

            def row_values(self, row):
                if row == 2:
                    return [''] * 43
                return []

            def update(self, a1_range, values, value_input_option=None):
                self.updates.append((a1_range, values, value_input_option))

        class FakeService:
            def __init__(self, sheet):
                self._sheet = sheet

            def is_available(self):
                return True

        sheet = FakeSheet()
        now = timezone.now().isoformat()
        case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-MJENGO',
            row_number=5,
            case_id='JBL-MJ-2026-SHEET-DROPDOWN',
            product_key='mjengo',
            product_label='Mjengo',
            client_name='Sheet Client',
            national_id='12345678',
            primary_phone='254712345678',
            branch='Nakuru',
            bro_name='BRO User',
            amount='100000',
            stage_values={
                'created': now,
                'mpesa_to_admin': now,
                'mpesa_verified': now,
                'ca_analysis_sent': now,
                'bro_response': now,
                'bm_tat_request': now,
                'tat_scheduled': now,
                'tat_held': now,
                'decision': 'Approved',
                'decision_ts': now,
                'minutes_shared': 'Yes',
                'minutes_shared_ts': now,
                'sanctions': 'Met',
                'sanctions_ts': now,
                'bro_applied': 'Met',
                'bro_applied_ts': now,
            },
            status='Active',
        )

        with patch('core.services.tat_tracker.get_sheets_service', return_value=FakeService(sheet)):
            sync_case_to_sheet(self.config, case)

        row = sheet.updates[0][1][0]
        self.assertEqual(row[17], 'Yes')
        self.assertEqual(row[20], 'Met')

    def test_sync_case_to_sheet_maps_legacy_mjengo_stage_timestamps_to_dropdown_values(self):
        class FakeSheet:
            def __init__(self):
                self.updates = []

            def row_values(self, row):
                if row == 2:
                    return [''] * 43
                return []

            def update(self, a1_range, values, value_input_option=None):
                self.updates.append((a1_range, values, value_input_option))

        class FakeService:
            def __init__(self, sheet):
                self._sheet = sheet

            def is_available(self):
                return True

        sheet = FakeSheet()
        now = timezone.now().isoformat()
        case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-MJENGO',
            row_number=5,
            case_id='JBL-MJ-2026-LEGACY-DROPDOWN',
            product_key='mjengo',
            product_label='Mjengo',
            client_name='Legacy Client',
            national_id='12345678',
            primary_phone='254712345678',
            branch='Nakuru',
            bro_name='BRO User',
            amount='100000',
            stage_values={
                'created': now,
                'decision': 'Approved',
                'decision_ts': now,
                'minutes_shared': now,
                'sanctions': 'Met',
                'sanctions_ts': now,
                'bro_applied': now,
            },
            status='Active',
        )

        with patch('core.services.tat_tracker.get_sheets_service', return_value=FakeService(sheet)):
            sync_case_to_sheet(self.config, case)

        row = sheet.updates[0][1][0]
        self.assertEqual(row[17], 'Yes')
        self.assertEqual(row[20], 'Met')

    def test_completed_dropdowns_use_done_timeline_indicators(self):
        source = Path('core/static/miniapp/tat_tracker.js').read_text(encoding='utf-8')

        self.assertIn("'stage-row' + (hasValue ? ' done' : field.editable ? ' editable' : ' locked')", source)
        self.assertIn('if (hasValue) {\n        indicatorHtml = `<span class="indicator-icon check-done">', source)

    def test_sync_case_to_sheet_skips_secondary_sheets_by_default(self):
        class FakeSheet:
            def row_values(self, _row):
                return [''] * 20

            def update(self, *_args, **_kwargs):
                return None

        class FakeService:
            _sheet = FakeSheet()

            def is_available(self):
                return True

        case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-Business',
            row_number=5,
            case_id='JBL-BS-2026-003',
            product_key='business',
            product_label='Business',
            client_name='Test Client',
            national_id='12345678',
            primary_phone='254712345678',
            branch='Nakuru',
            bro_name='BRO User',
            amount='10000',
            stage_values={'created': timezone.now().isoformat()},
            status='Active',
        )

        with patch('core.services.tat_tracker.get_sheets_service', return_value=FakeService()), \
             patch('core.services.tat_tracker.sync_case_index') as index_mock, \
             patch('core.services.tat_tracker.sync_audit_log') as audit_mock:
            sync_case_to_sheet(self.config, case)

        index_mock.assert_not_called()
        audit_mock.assert_not_called()

    def test_sync_case_to_sheet_appends_new_rows_without_scanning_existing_ids(self):
        class FakeSheet:
            def __init__(self):
                self.appended = []
                self.row_values_calls = []
                self.col_values_called = False

            def row_values(self, row):
                self.row_values_calls.append(row)
                return [''] * 20

            def col_values(self, _col):
                self.col_values_called = True
                return ['Case ID']

            def append_row(self, row, value_input_option=None):
                self.appended.append((row, value_input_option))
                return {'updates': {'updatedRange': 'TRACKER-Business!A6:AC6'}}

        class FakeService:
            def __init__(self, sheet):
                self._sheet = sheet

            def is_available(self):
                return True

        sheet = FakeSheet()
        case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-Business',
            case_id='JBL-BS-2026-005',
            product_key='business',
            product_label='Business',
            client_name='Test Client',
            national_id='12345678',
            primary_phone='254712345678',
            branch='Nakuru',
            bro_name='BRO User',
            amount='10000',
            stage_values={'created': timezone.now().isoformat()},
            status='Active',
        )

        with patch('core.services.tat_tracker.get_sheets_service', return_value=FakeService(sheet)):
            sync_case_to_sheet(self.config, case)

        self.assertEqual(case.row_number, 6)
        self.assertEqual(len(sheet.appended), 1)
        self.assertEqual(sheet.row_values_calls, [2])
        self.assertFalse(sheet.col_values_called)

    def test_sync_tat_batch_created_cases_appends_same_product_in_one_sheet_write(self):
        class FakeSheet:
            def __init__(self):
                self.row_values_calls = []
                self.appended_rows = []

            def row_values(self, row):
                self.row_values_calls.append(row)
                headers = [''] * 31
                headers[2] = 'ID NUMBER'
                headers[3] = 'PHONE NUMBER'
                return headers

            def append_rows(self, rows, value_input_option=None):
                self.appended_rows.append((rows, value_input_option))
                return {'updates': {'updatedRange': 'TRACKER-Business!A5:AE6'}}

        class FakeService:
            def __init__(self, sheet):
                self._sheet = sheet

            def is_available(self):
                return True

        sheet = FakeSheet()
        created_at = timezone.now().isoformat()
        case_one = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-Business',
            case_id='JBL-BS-2026-101',
            product_key='business',
            product_label='Business',
            client_name='First Client',
            national_id='12345678',
            primary_phone='254712345678',
            branch='Nakuru',
            bro_name='BRO User',
            amount='10000',
            stage_values={'created': created_at},
            status='Active',
        )
        case_two = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-Business',
            case_id='JBL-BS-2026-102',
            product_key='business',
            product_label='Business',
            client_name='Second Client',
            national_id='22345678',
            primary_phone='254722345678',
            branch='Embu',
            bro_name='BRO User',
            amount='20000',
            stage_values={'created': created_at},
            status='Active',
        )

        with patch('core.services.tat_tracker.get_sheets_service', return_value=FakeService(sheet)):
            result = sync_tat_batch_created_cases(self.config, [case_one, case_two])

        self.assertEqual(result, {'synced': 2, 'failed': []})
        self.assertEqual(sheet.row_values_calls, [2])
        self.assertEqual(len(sheet.appended_rows), 1)
        self.assertEqual(sheet.appended_rows[0][1], 'USER_ENTERED')
        self.assertEqual(len(sheet.appended_rows[0][0]), 2)
        case_one.refresh_from_db()
        case_two.refresh_from_db()
        self.assertEqual(case_one.row_number, 5)
        self.assertEqual(case_two.row_number, 6)

    def test_sync_case_to_sheet_prefers_stage_tat_headers_over_fixed_lag_columns(self):
        class FakeSheet:
            def __init__(self):
                self.updates = []

            def row_values(self, row):
                if row == 2:
                    headers = [''] * 34
                    headers[2] = 'ID NUMBER'
                    headers[3] = 'PHONE NUMBER'
                    headers[33] = 'MPESA sent to Admin TAT Minutes'
                    return headers
                return [''] * 34

            def update(self, a1_range, values, value_input_option=None):
                self.updates.append((a1_range, values, value_input_option))

        class FakeService:
            def __init__(self, sheet):
                self._sheet = sheet

            def is_available(self):
                return True

        sheet = FakeSheet()
        case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-Business',
            row_number=5,
            case_id='JBL-BS-2026-009',
            product_key='business',
            product_label='Business',
            client_name='Header Client',
            national_id='12345678',
            primary_phone='254712345678',
            branch='Nakuru',
            bro_name='BRO User',
            amount='10000',
            stage_values={
                'created': timezone.make_aware(timezone.datetime(2026, 7, 14, 8, 0)).isoformat(),
                'mpesa_to_admin': timezone.make_aware(timezone.datetime(2026, 7, 14, 8, 25)).isoformat(),
            },
            status='Active',
        )

        with patch('core.services.tat_tracker.get_sheets_service', return_value=FakeService(sheet)):
            sync_case_to_sheet(self.config, case)

        self.assertEqual(sheet.updates[0][0], 'A5:AH5')
        self.assertEqual(sheet.updates[0][1][0][33], 25.0)

    @override_settings(TAT_TRACKER_SYNC_SECONDARY_SHEETS=False)
    def test_secondary_sheet_override_syncs_index_but_not_unused_audit_log(self):
        class FakeSheet:
            def row_values(self, _row):
                return [''] * 20

            def update(self, *_args, **_kwargs):
                return None

        class FakeService:
            _sheet = FakeSheet()

            def is_available(self):
                return True

        self.config.workflow['sync_secondary_sheets'] = True
        case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-Business',
            row_number=5,
            case_id='JBL-BS-2026-004',
            product_key='business',
            product_label='Business',
            client_name='Test Client',
            national_id='12345678',
            primary_phone='254712345678',
            branch='Nakuru',
            bro_name='BRO User',
            amount='10000',
            stage_values={'created': timezone.now().isoformat()},
            status='Active',
        )

        with patch('core.services.tat_tracker.get_sheets_service', return_value=FakeService()), \
             patch('core.services.tat_tracker.sync_case_index') as index_mock, \
             patch('core.services.tat_tracker.sync_audit_log') as audit_mock:
            sync_case_to_sheet(self.config, case)

        index_mock.assert_called_once_with(self.config, case)
        audit_mock.assert_not_called()

    def test_calculated_tat_values_use_aware_datetimes_and_ongoing_now(self):
        case = TatTrackerCase(
            group_id=self.config.group_id,
            case_id='JBL-BS-2026-002',
            product_key='business',
            client_name='Ongoing Client',
            stage_values={'created': timezone.make_aware(timezone.datetime(2026, 7, 14, 8, 0)).isoformat()},
        )
        now = timezone.make_aware(timezone.datetime(2026, 7, 14, 20, 0))

        self.assertEqual(calculated_tat_minutes(case, now=now), Decimal('720.00'))
        self.assertEqual(calculated_tat_hours(case, now=now), Decimal('12.00'))
        self.assertEqual(calculated_tat_days(case, now=now), Decimal('0.50'))

    def test_rejected_tat_ends_at_decision_timestamp(self):
        case = TatTrackerCase(
            group_id=self.config.group_id,
            case_id='JBL-BS-2026-006',
            product_key='business',
            client_name='Rejected Client',
            status='Rejected',
            stage_values={
                'created': timezone.make_aware(timezone.datetime(2026, 7, 14, 8, 0)).isoformat(),
                'decision': 'Rejected',
                'decision_ts': timezone.make_aware(timezone.datetime(2026, 7, 14, 10, 30)).isoformat(),
            },
        )
        now = timezone.make_aware(timezone.datetime(2026, 7, 15, 8, 0))

        self.assertEqual(calculated_tat_minutes(case, now=now), Decimal('150.00'))

    def test_stage_tat_minutes_use_previous_stage_and_current_pending_stage(self):
        product = product_by_key('business')
        case = TatTrackerCase(
            group_id=self.config.group_id,
            case_id='JBL-BS-2026-007',
            product_key='business',
            client_name='Stage Client',
            stage_values={
                'created': timezone.make_aware(timezone.datetime(2026, 7, 14, 8, 0)).isoformat(),
                'mpesa_to_admin': timezone.make_aware(timezone.datetime(2026, 7, 14, 8, 45)).isoformat(),
            },
        )
        pending_now = timezone.make_aware(timezone.datetime(2026, 7, 14, 9, 30))

        self.assertEqual(stage_tat_minutes(case, product.stages[0]), Decimal('45.00'))
        self.assertEqual(stage_tat_minutes(case, product.stages[1], now=pending_now), Decimal('45.00'))

    def test_detail_payload_includes_stage_tat_and_sla_status(self):
        self.config.workflow['tat_targets_minutes'] = {
            'business': {'total': 120, 'stages': {'mpesa_to_admin': 60, 'mpesa_verified': 30}}
        }
        user = staff_user_for_payload(self.config, {'id': 111, 'username': 'bro_user'})
        case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-Business',
            case_id='JBL-BS-2026-008',
            product_key='business',
            product_label='Business',
            client_name='Target Client',
            branch='Nakuru',
            bro_name='BRO User',
            amount='10000',
            stage_values={
                'created': timezone.make_aware(timezone.datetime(2026, 7, 14, 8, 0)).isoformat(),
                'mpesa_to_admin': timezone.make_aware(timezone.datetime(2026, 7, 14, 8, 50)).isoformat(),
            },
            status='Active',
        )

        from core.services.tat_tracker import serialize_case_detail
        detail = serialize_case_detail(case, user, workflow=self.config.workflow)

        self.assertEqual(detail['summary']['target_minutes'], '120')
        self.assertEqual(detail['fields'][0]['tat_minutes'], '50.00')
        self.assertEqual(detail['fields'][0]['target_minutes'], '60')
        self.assertEqual(detail['fields'][0]['sla_status'], 'near')
        self.assertEqual(detail['fields'][1]['target_minutes'], '30')

    def test_next_role_alert_targets_pending_stage_role(self):
        data = {
            'summary': {
                'case_id': 'JBL-BS-2026-001',
                'product_key': 'business',
                'client_name': 'Test Client',
                'national_id': '12345678',
                'primary_phone': '0712345678',
                'branch': 'Nakuru',
                'next_stage_key': 'mpesa_to_admin',
            }
        }

        alert = next_role_alert(self.config, data)

        self.assertEqual(alert['role'], 'BRO')
        self.assertIn('TAT action needed: BRO', alert['text'])
        self.assertIn('Next step: MPESA sent to Admin', alert['text'])

    def test_next_role_alert_can_be_disabled_in_workflow(self):
        self.config.workflow['stage_alerts_enabled'] = False
        data = {'summary': {'product_key': 'business', 'next_stage_key': 'mpesa_to_admin'}}

        self.assertEqual(next_role_alert(self.config, data), {})

    @patch('core.api.views._post_telegram_reply')
    @patch('core.services.tat_tracker.sync_case_to_sheet')
    @patch('core.services.tat_tracker.validate_tat_telegram_webapp_init_data')
    def test_create_endpoint_alerts_next_stage_role(self, mock_auth, sync_mock, mock_reply):
        mock_auth.return_value = (True, '', {'id': 111, 'username': 'bro_user'})
        sync_mock.side_effect = self.mark_case_synced
        GroupRegistry._instance = None

        response = self.client.post(
            '/api/tat-tracker/create/',
            data=json.dumps({
                'group_id': self.config.group_id,
                'init_data': 'mock',
                'product_key': 'business',
                'branch': 'Nakuru',
                'client_name': 'Test Client',
            'national_id': '12345678',
            'primary_phone': '0712345678',
                'bro_name': 'BRO User',
                'amount': '10000',
            }),
            content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        mock_reply.assert_called_once()
        self.assertIn('TAT action needed: BRO', mock_reply.call_args.kwargs['text'])

    def test_tracker_identifier_headers_are_required_when_headers_exist(self):
        with self.assertRaisesRegex(ValueError, 'ID NUMBER'):
            validate_tracker_identity_headers(['Case ID', 'Client Name', 'Branch', 'BRO Name'])

    @patch('core.services.tat_tracker.sync_case_to_sheet')
    def test_create_case_normalizes_and_stores_customer_identifiers(self, sync_mock):
        sync_mock.side_effect = self.mark_case_synced
        user = staff_user_for_payload(self.config, {'id': 111, 'username': 'bro_user'})

        detail = create_case(self.config, user, {
            'product_key': 'business',
            'branch': 'Nakuru',
            'client_name': 'Test Client',
            'national_id': '12 345 678',
            'primary_phone': '+254 712 345 678',
            'bro_name': 'BRO User',
            'amount': '10000',
        })

        case = TatTrackerCase.objects.get(case_id=detail['summary']['case_id'])
        self.assertEqual(case.national_id, '12345678')
        self.assertEqual(case.primary_phone, '254712345678')
        self.assertEqual(detail['summary']['national_id'], '12345678')
        self.assertEqual(detail['summary']['primary_phone'], '254712345678')
        self.assertEqual(search_cases(self.config, user, '0712345678')[0]['case_id'], case.case_id)

    @patch('core.services.tat_tracker.sync_case_to_sheet')
    def test_create_case_rejects_invalid_customer_identifiers(self, sync_mock):
        user = staff_user_for_payload(self.config, {'id': 111, 'username': 'bro_user'})
        payload = {
            'product_key': 'business',
            'branch': 'Nakuru',
            'client_name': 'Test Client',
            'national_id': '1234',
            'primary_phone': '0712345678',
            'bro_name': 'BRO User',
            'amount': '10000',
        }

        with self.assertRaisesRegex(ValueError, 'ID number'):
            create_case(self.config, user, payload)
        self.assertFalse(sync_mock.called)
    @patch('core.services.tat_tracker.sync_case_to_sheet')
    def test_create_case_assigns_sequential_case_id(self, sync_mock):
        sync_mock.side_effect = self.mark_case_synced
        user = staff_user_for_payload(self.config, {'id': 111, 'username': 'bro_user'})
        first = create_case(self.config, user, {
            'product_key': 'business',
            'branch': 'Nakuru',
            'client_name': 'Test Client',
            'national_id': '12345678',
            'primary_phone': '0712345678',
            'bro_name': 'BRO User',
            'amount': '10000',
        })
        second = create_case(self.config, user, {
            'product_key': 'business',
            'branch': 'Nakuru',
            'client_name': 'Second Client',
            'national_id': '87654321',
            'primary_phone': '0712345679',
            'bro_name': 'BRO User',
            'amount': '10000',
        })
        self.assertEqual(first['summary']['case_id'], 'JBL-BS-2026-001')
        self.assertEqual(second['summary']['case_id'], 'JBL-BS-2026-002')
        self.assertEqual(TatTrackerCase.objects.count(), 2)
        self.assertEqual(sync_mock.call_count, 2)

    @patch('core.services.tat_tracker.sync_case_to_sheet')
    def test_create_case_retry_with_same_request_id_returns_existing_case(self, sync_mock):
        sync_mock.side_effect = self.mark_case_synced
        user = staff_user_for_payload(self.config, {'id': 111, 'username': 'bro_user'})
        payload = {
            'product_key': 'business',
            'branch': 'Nakuru',
            'client_name': 'Test Client',
            'national_id': '12345678',
            'primary_phone': '0712345678',
            'bro_name': 'BRO User',
            'amount': '10000',
            'client_request_id': 'req-123',
        }

        first = create_case(self.config, user, payload)
        second = create_case(self.config, user, payload)

        self.assertEqual(first['summary']['case_id'], second['summary']['case_id'])
        self.assertEqual(TatTrackerCase.objects.count(), 1)
        self.assertEqual(sync_mock.call_count, 1)

    @patch('core.services.tat_tracker.sync_case_to_sheet')
    def test_create_case_retry_does_not_resync_existing_unsynced_case(self, sync_mock):
        sync_mock.side_effect = self.mark_case_synced
        user = staff_user_for_payload(self.config, {'id': 111, 'username': 'bro_user'})
        payload = {
            'product_key': 'business',
            'branch': 'Nakuru',
            'client_name': 'Test Client',
            'national_id': '12345678',
            'primary_phone': '0712345678',
            'bro_name': 'BRO User',
            'amount': '10000',
            'client_request_id': 'req-unsynced-retry',
        }

        first = create_case(self.config, user, payload)
        case = TatTrackerCase.objects.get(case_id=first['summary']['case_id'])
        case.row_number = None
        case.sync_error = 'response lost after sheet append'
        case.save(update_fields=['row_number', 'sync_error', 'updated_at'])

        second = create_case(self.config, user, payload)

        self.assertEqual(first['summary']['case_id'], second['summary']['case_id'])
        self.assertEqual(TatTrackerCase.objects.count(), 1)
        self.assertEqual(sync_mock.call_count, 1)

    @patch('core.services.tat_tracker.sync_case_to_sheet')
    def test_create_case_rolls_back_when_primary_sheet_sync_fails(self, sync_mock):
        sync_mock.side_effect = RuntimeError('Primary sheet write failed')
        user = staff_user_for_payload(self.config, {'id': 111, 'username': 'bro_user'})

        with self.assertRaises(RuntimeError):
            create_case(self.config, user, {
                'product_key': 'business',
                'branch': 'Nakuru',
                'client_name': 'Test Client',
            'national_id': '12345678',
            'primary_phone': '0712345678',
                'bro_name': 'BRO User',
                'amount': '10000',
                'client_request_id': 'req-fail',
            })

        self.assertEqual(TatTrackerCase.objects.count(), 0)

    @patch('core.services.tat_tracker.sync_case_to_sheet')
    def test_stage_updates_are_role_and_sequence_controlled(self, sync_mock):
        sync_mock.side_effect = self.mark_case_synced
        bro = staff_user_for_payload(self.config, {'id': 111, 'username': 'bro_user'})
        admin = staff_user_for_payload(self.config, {'id': 222, 'username': 'admin_user'})
        detail = create_case(self.config, bro, {
            'product_key': 'business',
            'branch': 'Nakuru',
            'client_name': 'Test Client',
            'national_id': '12345678',
            'primary_phone': '0712345678',
            'bro_name': 'BRO User',
            'amount': '10000',
        })
        case_id = detail['summary']['case_id']

        with self.assertRaises(ValueError):
            update_case(self.config, admin, case_id, [{'field': 'mpesa_verified', 'value': 'STAMP'}])

        update_case(self.config, bro, case_id, [{'field': 'mpesa_to_admin', 'value': 'STAMP'}])
        updated = update_case(self.config, admin, case_id, [{'field': 'mpesa_verified', 'value': 'STAMP'}])
        self.assertEqual(updated['summary']['next_stage_key'], 'ca_analysis_sent')

    @patch('core.services.tat_tracker.sync_case_to_sheet')
    def test_assigned_role_can_change_a_dropdown_value_and_audit_the_change(self, sync_mock):
        sync_mock.side_effect = self.mark_case_synced
        sanctions_timestamp = timezone.make_aware(timezone.datetime(2026, 7, 18, 10, 0)).isoformat()
        case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-MJENGO',
            row_number=5,
            case_id='JBL-MJ-2026-EDIT-DROPDOWN',
            product_key='mjengo',
            product_label='Mjengo',
            client_name='Dropdown Client',
            branch='Nakuru',
            bro_name='BRO User',
            amount='100000',
            stage_values={
                'created': timezone.now().isoformat(),
                'mpesa_to_admin': timezone.now().isoformat(),
                'mpesa_verified': timezone.now().isoformat(),
                'ca_analysis_sent': timezone.now().isoformat(),
                'bro_response': timezone.now().isoformat(),
                'bm_tat_request': timezone.now().isoformat(),
                'tat_scheduled': timezone.now().isoformat(),
                'tat_held': timezone.now().isoformat(),
                'decision': 'Approved',
                'decision_ts': timezone.now().isoformat(),
                'minutes_shared': 'Yes',
                'minutes_shared_ts': timezone.now().isoformat(),
                'sanctions': 'Pending',
                'sanctions_ts': sanctions_timestamp,
            },
        )
        loan_approver = {
            'name': 'Loan Approver',
            'telegram_id': '444',
            'roles': ['LOAN_APPROVER'],
            'branches': ['Nakuru'],
            'products': ['mjengo'],
        }

        detail = update_case(
            self.config,
            loan_approver,
            case.case_id,
            [{'field': 'sanctions', 'value': 'Met'}],
        )

        case.refresh_from_db()
        sanctions_field = next(field for field in detail['fields'] if field['key'] == 'sanctions')
        event = case.events.get(stage_key='sanctions')
        self.assertTrue(sanctions_field['editable'])
        self.assertEqual(case.stage_values['sanctions'], 'Met')
        self.assertEqual(case.stage_values['sanctions_ts'], sanctions_timestamp)
        self.assertEqual(event.old_value, 'Pending')
        self.assertEqual(event.new_value, 'Met')

    @patch('core.services.tat_tracker.sync_case_to_sheet')
    def test_mjengo_minutes_shared_writes_dropdown_value_and_internal_timestamp(self, sync_mock):
        sync_mock.side_effect = self.mark_case_synced
        case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-MJENGO',
            row_number=5,
            case_id='JBL-MJ-2026-MINUTES-DROPDOWN',
            product_key='mjengo',
            product_label='Mjengo',
            client_name='Minutes Client',
            branch='Nakuru',
            bro_name='BRO User',
            amount='100000',
            stage_values={
                'created': timezone.now().isoformat(),
                'mpesa_to_admin': timezone.now().isoformat(),
                'mpesa_verified': timezone.now().isoformat(),
                'ca_analysis_sent': timezone.now().isoformat(),
                'bro_response': timezone.now().isoformat(),
                'bm_tat_request': timezone.now().isoformat(),
                'tat_scheduled': timezone.now().isoformat(),
                'tat_held': timezone.now().isoformat(),
                'decision': 'Approved',
                'decision_ts': timezone.now().isoformat(),
            },
        )
        secretary = {
            'name': 'Secretary',
            'telegram_id': '333',
            'roles': ['SECRETARY'],
            'branches': ['Nakuru'],
            'products': ['mjengo'],
        }

        update_case(self.config, secretary, case.case_id, [{'field': 'minutes_shared', 'value': 'Yes'}])

        case.refresh_from_db()
        self.assertEqual(case.stage_values['minutes_shared'], 'Yes')
        self.assertTrue(parse_iso_datetime(case.stage_values['minutes_shared_ts']))
        self.assertIsNotNone(stage_tat_minutes(case, stage_by_key(product_by_key('mjengo'), 'minutes_shared')))

    @patch('core.services.tat_tracker.sync_case_to_sheet')
    def test_mjengo_bro_applied_writes_dropdown_value_and_internal_timestamp(self, sync_mock):
        sync_mock.side_effect = self.mark_case_synced
        case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-MJENGO',
            row_number=5,
            case_id='JBL-MJ-2026-BRO-APPLIED-DROPDOWN',
            product_key='mjengo',
            product_label='Mjengo',
            client_name='Applied Client',
            branch='Nakuru',
            bro_name='BRO User',
            amount='100000',
            stage_values={
                'created': timezone.now().isoformat(),
                'mpesa_to_admin': timezone.now().isoformat(),
                'mpesa_verified': timezone.now().isoformat(),
                'ca_analysis_sent': timezone.now().isoformat(),
                'bro_response': timezone.now().isoformat(),
                'bm_tat_request': timezone.now().isoformat(),
                'tat_scheduled': timezone.now().isoformat(),
                'tat_held': timezone.now().isoformat(),
                'decision': 'Approved',
                'decision_ts': timezone.now().isoformat(),
                'minutes_shared': 'Yes',
                'minutes_shared_ts': timezone.now().isoformat(),
                'sanctions': 'Met',
                'sanctions_ts': timezone.now().isoformat(),
            },
        )
        bro = {
            'name': 'BRO User',
            'telegram_id': '111',
            'roles': ['BRO'],
            'branches': ['Nakuru'],
            'products': ['mjengo'],
        }

        update_case(self.config, bro, case.case_id, [{'field': 'bro_applied', 'value': 'Met'}])

        case.refresh_from_db()
        self.assertEqual(case.stage_values['bro_applied'], 'Met')
        self.assertTrue(parse_iso_datetime(case.stage_values['bro_applied_ts']))
        self.assertIsNotNone(stage_tat_minutes(case, stage_by_key(product_by_key('mjengo'), 'bro_applied')))

    @patch('core.services.tat_tracker.sync_case_to_sheet')
    def test_register_approval_records_a_completion_timestamp_for_its_tat(self, sync_mock):
        sync_mock.side_effect = self.mark_case_synced
        case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-Business',
            row_number=5,
            case_id='JBL-BS-2026-REGISTER-APPROVAL',
            product_key='business',
            product_label='Business',
            client_name='Approval Client',
            branch='Nakuru',
            bro_name='BRO User',
            amount='10000',
            stage_values={
                'created': timezone.now().isoformat(),
                'mpesa_to_admin': timezone.now().isoformat(),
                'mpesa_verified': timezone.now().isoformat(),
                'ca_analysis_sent': timezone.now().isoformat(),
                'bro_response': timezone.now().isoformat(),
                'bm_response': timezone.now().isoformat(),
                'bro_applied': timezone.now().isoformat(),
                'disbursement_register': '10:00am',
                'register_ts': timezone.now().isoformat(),
            },
        )
        loan_approver = {
            'name': 'Loan Approver',
            'telegram_id': '444',
            'roles': ['LOAN_APPROVER'],
            'branches': ['Nakuru'],
            'products': ['business'],
        }

        update_case(
            self.config,
            loan_approver,
            case.case_id,
            [{'field': 'register_approved', 'value': 'Approved'}],
        )

        case.refresh_from_db()
        self.assertEqual(case.stage_values['register_approved'], 'Approved')
        self.assertTrue(parse_iso_datetime(case.stage_values['register_approved_ts']))
        self.assertIsNotNone(stage_tat_minutes(case, stage_by_key(product_by_key('business'), 'register_approved')))

    @patch('core.services.tat_tracker.sync_case_to_sheet')
    def test_changing_a_decision_dropdown_reopens_a_rejected_case(self, sync_mock):
        sync_mock.side_effect = self.mark_case_synced
        case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-MJENGO',
            row_number=5,
            case_id='JBL-MJ-2026-REOPEN-DROPDOWN',
            product_key='mjengo',
            product_label='Mjengo',
            client_name='Decision Client',
            branch='Nakuru',
            bro_name='BRO User',
            amount='100000',
            status='Rejected',
            stage_values={
                'created': timezone.now().isoformat(),
                'mpesa_to_admin': timezone.now().isoformat(),
                'mpesa_verified': timezone.now().isoformat(),
                'ca_analysis_sent': timezone.now().isoformat(),
                'bro_response': timezone.now().isoformat(),
                'bm_tat_request': timezone.now().isoformat(),
                'tat_scheduled': timezone.now().isoformat(),
                'tat_held': timezone.now().isoformat(),
                'decision': 'Rejected',
                'decision_ts': timezone.now().isoformat(),
            },
        )
        chair = {
            'name': 'Chair User',
            'telegram_id': '555',
            'roles': ['CHAIR'],
            'branches': ['Nakuru'],
            'products': ['mjengo'],
        }

        detail = update_case(self.config, chair, case.case_id, [{'field': 'decision', 'value': 'Approved'}])

        case.refresh_from_db()
        self.assertEqual(case.status, 'Active')
        self.assertEqual(detail['summary']['next_stage_key'], 'minutes_shared')
        self.assertEqual(case.events.get(stage_key='decision').old_value, 'Rejected')


class TatTrackerRepairTest(TestCase):
    def setUp(self):
        self.config = GroupSheetConfiguration.objects.create(
            group_id='-100tat-repair',
            display_name='TAT Repair Test',
            sheet_id='sheet-repair',
            sheet_name='TRACKER-Business',
            workflow={'type': 'tat_tracker', 'products': ['business', 'logbook']},
        )
        self.repairable_case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-Business',
            row_number=5,
            case_id='JBL-BS-2026-REPAIR',
            product_key='business',
            product_label='Business',
            client_name='Repairable Client',
            branch='Nakuru',
            status='Active',
            stage_values={'created': timezone.now().isoformat()},
        )
        TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-LOGBOOK',
            row_number=6,
            case_id='JBL-LB-2026-REPAIR',
            product_key='logbook',
            product_label='Logbook',
            client_name='Other Product',
            branch='Nakuru',
            status='Active',
            stage_values={'created': timezone.now().isoformat()},
        )
        TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            sheet_id=self.config.sheet_id,
            sheet_name='TRACKER-Business',
            case_id='JBL-BS-2026-UNLINKED',
            product_key='business',
            product_label='Business',
            client_name='Unlinked Client',
            branch='Nakuru',
            status='Active',
            stage_values={'created': timezone.now().isoformat()},
        )

    @patch('core.services.tat_tracker.sync_case_to_sheet')
    def test_repair_resync_limits_to_linked_cases_and_selected_product(self, sync_case):
        result = resync_tat_tracker_cases(self.config, product_key='business')

        self.assertEqual(result, {
            'total_candidates': 1,
            'candidates': 1,
            'synced': 1,
            'skipped_unlinked': 1,
            'failed': [],
            'offset': 0,
            'next_offset': None,
        })
        sync_case.assert_called_once_with(self.config, self.repairable_case)

    @patch('core.services.tat_tracker.sync_case_to_sheet')
    def test_repair_dry_run_does_not_write_to_google_sheets(self, sync_case):
        result = resync_tat_tracker_cases(self.config, dry_run=True)

        self.assertEqual(result['candidates'], 2)
        self.assertEqual(result['synced'], 0)
        self.assertEqual(result['skipped_unlinked'], 1)
        sync_case.assert_not_called()

    def test_apps_script_contains_an_explicit_formula_only_repair(self):
        source = (Path(__file__).resolve().parent.parent / 'tat_tracker_apps_script.gs').read_text(encoding='utf-8')

        self.assertIn("'Remove legacy TAT formulas (safe)'", source)
        self.assertIn('function clearLegacyTatFormulas()', source)
        self.assertIn('range.getFormulas()', source)
        self.assertIn('getRangeList(formulaCells).clearContent()', source)

    @patch('core.management.commands.resync_tat_tracker_cases.resync_tat_tracker_cases')
    def test_repair_command_passes_dry_run_without_writing(self, resync):
        resync.return_value = {'candidates': 2, 'synced': 0, 'skipped_unlinked': 1, 'failed': []}
        output = StringIO()

        call_command(
            'resync_tat_tracker_cases',
            f'--group-id={self.config.group_id}',
            '--product',
            'business',
            '--dry-run',
            stdout=output,
        )

        resync.assert_called_once_with(
            self.config,
            product_key='business',
            case_ids=[],
            dry_run=True,
            limit=None,
            offset=0,
        )
        self.assertIn("'synced': 0", output.getvalue())


class TatTrackerRepairAdminTest(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username='repair-admin',
            email='repair-admin@example.test',
            password='password',
        )
        self.config = GroupSheetConfiguration.objects.create(
            group_id='-100tat-admin-repair',
            display_name='TAT Admin Repair',
            sheet_id='sheet-admin-repair',
            sheet_name='TRACKER-Business',
            workflow={'type': 'tat_tracker', 'products': ['business']},
        )
        self.url = reverse('admin:core_groupsheetconfiguration_tat_repair', args=[self.config.pk])
        self.client.force_login(self.user)

    @patch('core.admin.resync_tat_tracker_cases')
    def test_repair_page_previews_a_bounded_batch_without_sheet_writes(self, resync):
        resync.return_value = {
            'total_candidates': 30,
            'candidates': 25,
            'synced': 0,
            'skipped_unlinked': 2,
            'failed': [],
            'offset': 0,
            'next_offset': 25,
        }

        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Preview only')
        self.assertContains(response, 'Type REPAIR')
        resync.assert_called_once_with(self.config, dry_run=True, limit=25, offset=0, product_key='')

    @patch('core.admin.resync_tat_tracker_cases')
    def test_repair_page_requires_confirmation_before_writing(self, resync):
        response = self.client.post(self.url, {'confirm': 'no'})

        self.assertEqual(response.status_code, 200)
        resync.assert_not_called()

    @patch('core.admin.resync_tat_tracker_cases')
    def test_repair_page_writes_only_after_typed_confirmation(self, resync):
        resync.return_value = {
            'total_candidates': 1,
            'candidates': 1,
            'synced': 0,
            'skipped_unlinked': 0,
            'failed': [],
            'offset': 0,
            'next_offset': None,
        }
        self.client.get(self.url + '?product=business')
        resync.reset_mock()
        resync.return_value = {
            'total_candidates': 1,
            'candidates': 1,
            'synced': 1,
            'skipped_unlinked': 0,
            'failed': [],
            'offset': 0,
            'next_offset': None,
        }

        response = self.client.post(self.url, {'confirm': 'REPAIR', 'product': 'business', 'offset': '0'})

        self.assertEqual(response.status_code, 302)
        resync.assert_called_once_with(self.config, dry_run=False, limit=25, offset=0, product_key='business')

    @patch('core.admin.resync_tat_tracker_cases')
    def test_repair_page_rejects_a_write_without_matching_preview(self, resync):
        response = self.client.post(self.url, {'confirm': 'REPAIR', 'product': 'business', 'offset': '0'})

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Preview this exact batch')
        resync.assert_not_called()
