from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.contrib.auth import get_user_model

from core.services.sheet_columns import verify_cells
from core.services.sheets import GoogleSheetsService
from core.models import GroupSheetConfiguration, JawabuFarmerMaster


class Worksheet:
    def __init__(self, headers, row):
        self.rows = [headers, row]
        self.writes = []

    def row_values(self, number, **kwargs):
        return list(self.rows[number - 1])

    def col_values(self, column):
        return [row[column - 1] if column <= len(row) else '' for row in self.rows]

    def update(self, cell, rows, **kwargs):
        import re
        letters, number = re.match(r'([A-Z]+)(\d+)', cell).groups()
        start = 0
        for letter in letters:
            start = start * 26 + ord(letter) - 64
        row = self.rows[int(number) - 1]
        while len(row) < start - 1 + len(rows[0]): row.append('')
        row[start - 1:start - 1 + len(rows[0])] = rows[0]
        self.writes.append(cell)


class CorrectionSheetTests(SimpleTestCase):
    def test_real_complaint_writer_clears_location_and_updates_biodata_without_touching_identity_or_formula(self):
        service = GoogleSheetsService(sheet_schema={'schema_version':2})
        headers = ['Unowned formula', *reversed(service.sheet_columns)]
        row = ['=1+1'] + ['Old'] * (len(headers) - 1)
        row[headers.index('Complaint ID')] = 'CMP-SYNTHETIC'
        sheet = Worksheet(headers, row)
        service._sheet = sheet
        with patch.object(service, 'is_available', return_value=True):
            self.assertTrue(service.update_case_row('CMP-SYNTHETIC', {'county':'', 'sub_county':'', 'village':'',
                'customer_name':'Synthetic Corrected', 'secondary_phone':'', 'complaint_id':'Never replace', 'days_open':0}))
        for label in ['County','Constituency','Village','Secondary Phone No']:
            self.assertEqual(sheet.rows[1][headers.index(label)], '')
        self.assertEqual(sheet.rows[1][headers.index('Customer Name')], 'SYNTHETIC CORRECTED')
        self.assertEqual(sheet.rows[1][headers.index('Complaint ID')], 'CMP-SYNTHETIC')
        self.assertEqual(sheet.rows[1][0], '=1+1')
        self.assertEqual(sheet.rows[1][headers.index('Days Open')], 0)

    def test_readback_detects_ignored_clear_and_accepts_missing_trailing_blanks_zero_and_false(self):
        sheet = Worksheet(['A'], ['Old'])
        with self.assertRaisesMessage(ValueError, 'readback'):
            verify_cells(sheet, 2, {0:''})
        sheet.rows[1] = [0, False]
        verify_cells(sheet, 2, {0:0, 1:False, 2:''})


class PortalRefreshTests(TestCase):
    def test_deleted_portal_record_cannot_be_republished_or_refreshed(self):
        from core.services.portal_publication import refresh_farmer_publication
        from core.services.jawabu_pipeline import sync_farmer_to_master_sheet
        case = JawabuFarmerMaster.objects.create(customer_name='Synthetic deleted')
        JawabuFarmerMaster.objects.filter(pk=case.pk).delete()
        with patch('core.services.sheets.GoogleSheetsService.get_instance') as google:
            self.assertFalse(sync_farmer_to_master_sheet(case))
            self.assertEqual(refresh_farmer_publication(case, request_id='deleted'), [])
            google.assert_not_called()

    def test_refresh_api_rejects_actor_without_portal_retry_grant(self):
        import json
        from django.test import override_settings
        from core.models import UserProfile, IntegrationOperation
        from core.tests_telegram_authentication import BOT_TOKEN, signed_init_data
        actor = get_user_model().objects.create_user(username='synthetic-no-refresh-grant')
        UserProfile.objects.create(user=actor,telegram_id='997797')
        case = JawabuFarmerMaster.objects.create(customer_name='Synthetic inaccessible')
        with override_settings(TELEGRAM_BOT_TOKEN=BOT_TOKEN, SECURE_SSL_REDIRECT=False,PORTAL_WEBAPP_REQUIRE_TELEGRAM_AUTH=True):
            response = self.client.post('/api/portal/publication/attempt/',
                json.dumps({'refresh_snapshot':True,'farmer_id':str(case.pk),'client_request_id':'synthetic-denied'}),
                content_type='application/json',HTTP_X_TELEGRAM_INIT_DATA=signed_init_data(user={'id':997797}),
                HTTP_IDEMPOTENCY_KEY='synthetic-denied')
        self.assertEqual(response.status_code,403,response.content)
        self.assertFalse(IntegrationOperation.objects.filter(source_id=str(case.pk)).exists())

    def test_refresh_after_success_coalesces_and_keeps_case_revision(self):
        from core.services.portal_publication import reserve_farmer_publication, refresh_farmer_publication
        actor = get_user_model().objects.create_superuser(username='synthetic-refresh')
        group = GroupSheetConfiguration.objects.create(group_id='synthetic-refresh', sheet_id='synthetic',
            workflow={'type':'jawabu', 'master_sync_enabled':True})
        case = JawabuFarmerMaster.objects.create(group_configuration=group, customer_name='Synthetic', workflow_revision=4)
        original = reserve_farmer_publication(case)[0]
        original.status = 'succeeded'; original.save(update_fields=['status'])
        first = refresh_farmer_publication(case, request_id='synthetic-refresh', actor=actor)
        second = refresh_farmer_publication(case, request_id='synthetic-refresh', actor=actor)
        self.assertEqual(first[0].pk, second[0].pk)
        self.assertNotEqual(first[0].pk, original.pk)
        case.refresh_from_db()
        self.assertEqual(case.workflow_revision, 4)
