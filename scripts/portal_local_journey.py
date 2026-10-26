"""Connected synthetic Portal journey; invoked by portal_local_audit.py only."""
from __future__ import annotations

from contextlib import ExitStack
import csv
from datetime import timedelta
from hashlib import sha256
import hmac
from io import BytesIO, StringIO
import json
import time
import traceback
from urllib.parse import urlencode
from unittest.mock import patch


def run(output):
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.core.files.base import ContentFile
    from django.core.files.uploadedfile import SimpleUploadedFile
    from django.test import Client
    from django.urls import reverse
    from django.utils import timezone
    from openpyxl import Workbook, load_workbook
    from reportlab.pdfgen.canvas import Canvas
    from core.models import (
        AccessGrant, GroupSheetConfiguration, IntegrationOperation,
        JawabuFarmerMaster, JawabuFarmerUploadBatch, PaymentDocumentTemplate,
        RequisitionBatch, RequisitionTemplate, UserProfile,
    )
    from core.tests import FakeMasterDataSheet, FakeJawabuService
    from core.tests_payment_documents import synthetic_payment_template_bytes
    from core.services.order_approval import GoogleDriveMediaStorage
    from core.services.portal_imports import farmup_revision_token, attempt_import_archive
    from core.services.portal_publication import queued_publication_operations, attempt_publication
    from core.services.jawabu_pipeline import current_pipeline_state_label, JBL_FORWARD_STATUS
    from hb_operations.models import HomeBiogasAction
    from payments.models import PaymentBatch

    evidence = {'steps': [], 'status': 'running', 'network': 'blocked',
                'business_logic_patched': False, 'database': settings.DATABASES['default']['NAME']}
    def record(name, **details):
        evidence['steps'].append({'step': name, **details})
        (output / 'journey.json').write_text(json.dumps(evidence, indent=2, default=str), encoding='utf-8')
        print(name, json.dumps(details, default=str), flush=True)

    assert not JawabuFarmerMaster.objects.exists(), 'Journey requires its dedicated empty database'
    settings.TELEGRAM_BOT_TOKEN = '000000:synthetic-local-audit-only'
    settings.GOOGLE_DRIVE_MEDIA_FOLDER_ID = 'local-audit-root'
    settings.PORTAL_PUBLICATION_MIN_SPACING_SECONDS = 0
    settings.RUNNING_TESTS = True
    drive_dir = output / 'drive'
    sheet_dir = output / 'sheets'
    drive_dir.mkdir(exist_ok=True)
    sheet_dir.mkdir(exist_ok=True)
    drive_files = []
    def upload(storage, data, *, filename, mime_type, **kwargs):
        if hasattr(data, 'read'):
            data.seek(0)
            data = data.read()
        data = bytes(data)
        file_id = sha256(data).hexdigest()
        (drive_dir / file_id).write_bytes(data)
        drive_files.append({'id': file_id, 'filename': filename, 'mime_type': mime_type, 'size': len(data)})
        (drive_dir / 'manifest.json').write_text(json.dumps(drive_files, indent=2), encoding='utf-8')
        return file_id, f'https://drive.invalid/local/{file_id}'
    def download(storage, file_id):
        return (drive_dir / file_id).read_bytes()

    headers = ['No.', 'Customer Name', 'National ID', 'Primary Phone', 'County', 'Sub-County',
               'Village', 'Branch', 'Case ID', 'Current Pipeline State', 'JBL Visit Date',
               'Credit Analysis', 'Final Decision', 'Order No', 'Invoice Number', 'Payment No',
               'Installation Status', 'Installation Date', 'Commissioning Status', 'Commissioning Date',
               'Balance Due', 'Deposit Paid to HBG', 'CUSTOMER NO', 'NAME (IMAB)', 'Payment Product',
               'Mode of Payment', 'Requisition Date']
    sheets = {}
    for tab in ('Master Data', 'Eco-conserve', 'Orders'):
        sheet = FakeMasterDataSheet(headers)
        sheet.values = [list(headers)]
        sheets[tab] = sheet
    def sheet_service(*, sheet_id, sheet_name, **kwargs):
        assert sheet_id == 'local-audit-sheet', 'Unexpected spreadsheet destination'
        return FakeJawabuService(sheets[sheet_name])
    def save_sheets():
        for tab, sheet in sheets.items():
            with (sheet_dir / f'{tab}.csv').open('w', newline='', encoding='utf-8') as stream:
                csv.writer(stream).writerows(sheet.values)
    def drain(name):
        attempts = 0
        while (operation := queued_publication_operations().first()) is not None:
            result = attempt_publication(operation)
            attempts += 1
            assert not result.get('error'), result
            assert attempts < 150, 'Publication queue stopped progressing'
        save_sheets()
        record(name, attempts=attempts, rows={tab: len(sheet.values) - 1 for tab, sheet in sheets.items()})

    group = GroupSheetConfiguration.objects.create(
        group_id='local-synthetic-portal', display_name='Synthetic Portal audit', enabled=True,
        sheet_id='local-audit-sheet', sheet_name='Master Data',
        workflow={'type': 'jawabu_homebiogas', 'master_sync_enabled': True,
                  'master_sheet_id': 'local-audit-sheet', 'master_sheet_name': 'Master Data',
                  'eco_conserve_sheet_name': 'Eco-conserve', 'master_header_row': 1,
                  'master_data_start_row': 2},
    )
    clients = {}
    for number, role in enumerate(('IT', 'OPERATIONS_ADMIN', 'JBL_OFFICER', 'CREDIT_ANALYST', 'BUSINESS_ADMIN', 'HB_STAFF'), 1):
        actor = get_user_model().objects.create_user(username=f'synthetic-{role.lower()}', first_name=f'Synthetic {role}')
        UserProfile.objects.update_or_create(user=actor, defaults={'telegram_id': str(900000000 + number)})
        AccessGrant.objects.create(user=actor, workflow='jawabu_portal', role=role, group_configuration=group)
        fields = {'auth_date': str(int(time.time())), 'user': json.dumps({'id': 900000000 + number, 'first_name': actor.first_name})}
        secret = hmac.new(b'WebAppData', settings.TELEGRAM_BOT_TOKEN.encode(), sha256).digest()
        fields['hash'] = hmac.new(secret, '\n'.join(f'{key}={value}' for key, value in sorted(fields.items())).encode(), sha256).hexdigest()
        clients[role] = Client(HTTP_X_TELEGRAM_INIT_DATA=urlencode(fields))

    def api(role, name, data=None, *, args=(), expected=200, multipart=False, key=None):
        url = reverse(name, args=args)
        if data is None:
            response = clients[role].get(url)
        else:
            payload = {**data, 'client_request_id': key or f'local-audit-{len(evidence["steps"]):03}-{name}'}
            headers = {'HTTP_X_REQUEST_ID': payload['client_request_id']}
            response = clients[role].post(url, payload, **headers) if multipart else clients[role].post(url, json.dumps(payload), content_type='application/json', **headers)
        try:
            result = response.json()
        except ValueError:
            result = {'body': response.content[:300].decode(errors='replace')}
        record(name, role=role, status=response.status_code, expected=expected,
               ok=result.get('ok'), error=result.get('error'))
        assert response.status_code == expected, result
        if expected < 300:
            assert result.get('ok', True), result
        return result

    def csv_bytes(columns, rows):
        stream = StringIO()
        writer = csv.writer(stream)
        writer.writerow(columns)
        writer.writerows(rows)
        return stream.getvalue().encode()

    def pdf(text):
        stream = BytesIO()
        canvas = Canvas(stream)
        canvas.setTitle('Synthetic local Portal audit')
        for index, line in enumerate(text.splitlines()):
            canvas.drawString(45, 800 - index * 18, line)
        canvas.save()
        return stream.getvalue()

    def photo(number):
        from PIL import Image, ImageDraw
        image = Image.new('RGB', (800, 600), (30 * number, 60, 150))
        ImageDraw.Draw(image).text((50, 50), f'SYNTHETIC CAPTURE {number}', fill='white')
        stream = BytesIO()
        image.save(stream, format='JPEG')
        return SimpleUploadedFile(f'synthetic-{number}.jpg', stream.getvalue(), content_type='image/jpeg')

    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(GoogleDriveMediaStorage, 'upload', upload))
            stack.enter_context(patch.object(GoogleDriveMediaStorage, 'download', download))
            stack.enter_context(patch('core.services.sheets.GoogleSheetsService.get_instance', side_effect=sheet_service))
            # Telegram transport is a local sink; authentication remains real HMAC verification.
            stack.enter_context(patch('requests.post', side_effect=OSError('Synthetic audit: Telegram delivery disabled')))
            api('JBL_OFFICER', 'portal_meta')
            from requisitions.models import OrderSequenceState
            from payments.models import PaymentSequenceState
            for partner in ('HB', 'ECOCONSERVE'):
                OrderSequenceState.objects.create(group_configuration=group, partner=partner, next_number=1)
                workbook = Workbook()
                ws = workbook.active
                ws.append(['Synthetic requisition'])
                ws['A4'], ws['H4'] = 'Date:', 'Order No:'
                for col, title in enumerate(('No.', 'Name of the Customer', 'Contact No', 'ID No', 'Credit Analysis', 'Callup Comment', 'County', 'Location', 'HBG', 'JBL', 'Sales Person'), 1):
                    ws.cell(7, col, title)
                for row in range(9, 14):
                    ws.cell(row, 1, row - 8)
                ws.cell(14, 1, 'Total')
                stream = BytesIO()
                workbook.save(stream)
                template = RequisitionTemplate.objects.create(name=f'Synthetic {partner}', fulfillment_partner=partner, is_active=True)
                template.file.save(f'synthetic-{partner}.xlsx', ContentFile(stream.getvalue()))
            PaymentSequenceState.objects.create(group_configuration=group, next_number=1)
            template = PaymentDocumentTemplate.objects.create(name='Synthetic payment', is_active=True)
            template.file.save('synthetic-payment.xlsx', ContentFile(synthetic_payment_template_bytes()))

            identities = [('SYNTHETIC HB APPLICANT', '99000001', '254700000001', 'Kiambu', 'Limuru', 'Synthetic HB'),
                          ('SYNTHETIC ECO APPLICANT', '99000002', '254700000002', 'Nakuru', 'Nakuru', 'Eco-conserve')]
            sysup = csv_bytes(['Customer ID', 'Name', 'Mobile No', 'ID NO', 'Branch', 'Loan Officer', 'Product Name', 'LGF Balance'],
                              [[str(990001 + i), name, phone, identity, branch, 'Synthetic officer', 'HomeBiogas', '0']
                               for i, (name, identity, phone, county, branch, sales) in enumerate(identities)])
            staged = api('IT', 'portal_import_stage', {'file': SimpleUploadedFile('synthetic-sysup.csv', sysup)}, args=('sysup',), multipart=True, expected=201)
            sys_batch = JawabuFarmerUploadBatch.objects.get(pk=staged['batch']['id'])
            assert not JawabuFarmerMaster.objects.exists()
            record('sysup_does_not_create_leads', rows=sys_batch.total_rows)
            farmup = csv_bytes(['Full Name', 'ID NUMBER', 'HBG Hub', 'Branch', 'Mobile', 'Phone', 'Actual Receipts', 'Sign Date', 'Sales Person'],
                               [[name, identity, county, branch, phone, '254711' + phone[-6:], '5000', (timezone.localdate() - timedelta(days=2)).strftime('%d/%m/%Y'), sales]
                                for name, identity, phone, county, branch, sales in identities])
            staged = api('OPERATIONS_ADMIN', 'portal_farmup_stage', {'file': SimpleUploadedFile('synthetic-farmup.csv', farmup), 'period': timezone.localdate().strftime('%Y-%m')}, multipart=True, expected=201)
            farm_batch = JawabuFarmerUploadBatch.objects.get(pk=staged['batch']['id'])
            rows = [{**row, 'approved': True, 'warning_acknowledged': True} for row in farm_batch.parsed_rows]
            payload = {'rows': rows, 'revision_token': farmup_revision_token(farm_batch)}
            api('OPERATIONS_ADMIN', 'portal_farmup_validate', payload, args=(farm_batch.pk,))
            api('OPERATIONS_ADMIN', 'portal_farmup_commit', payload, args=(farm_batch.pk,), key='local-farmup-commit')
            api('OPERATIONS_ADMIN', 'portal_farmup_commit', payload, args=(farm_batch.pk,), key='local-farmup-commit')
            assert JawabuFarmerMaster.objects.count() == 2
            for batch in (sys_batch, farm_batch):
                operation = IntegrationOperation.objects.get(source_id=str(batch.pk), operation_type='portal_import_drive_archive')
                archive_result = attempt_import_archive(str(operation.pk))
                assert not archive_result.get('error'), archive_result
            from core.services.system_export import resolve_system_export_row
            sys_rows = []
            for row in sys_batch.parsed_rows:
                resolved = resolve_system_export_row(dict(row))
                farmer = JawabuFarmerMaster.objects.get(national_id=row['ID NO'])
                sys_rows.append({**resolved, 'approved': True, 'Matched Farmer ID': str(farmer.pk), 'case_revision': farmer.workflow_revision})
            api('OPERATIONS_ADMIN', 'portal_import_commit', {'rows': sys_rows, 'portal_revision': sys_batch.portal_revision}, args=(sys_batch.pk,))
            drain('initial_sheet_publication')

            orders, receipts = [], []
            for name, identity, phone, county, branch, sales in identities:
                farmer = JawabuFarmerMaster.objects.get(national_id=identity)
                api('OPERATIONS_ADMIN', 'portal_set_final_decision', {'final_decision': 'Approved', 'workflow_revision': farmer.workflow_revision}, args=(farmer.pk,), expected=403)
                visit = {'workflow_revision': farmer.workflow_revision, 'visit_date': timezone.localdate().isoformat(),
                         'visit_status': JBL_FORWARD_STATUS, 'officer': 'Synthetic officer', 'county': county,
                         'sub_county': 'Limuru' if county == 'Kiambu' else 'Nakuru Town East', 'village': 'Synthetic village',
                         'location_unavailable_reason': 'Synthetic local audit without device GPS',
                         'client_id_front': photo(1), 'client_id_back': photo(2),
                         'laf_page_1': photo(3), 'laf_page_2': photo(4),
                         'jbl_visit_photo_files': photo(5)}
                api('JBL_OFFICER', 'portal_complete_jbl_visit', visit, args=(farmer.pk,), multipart=True)
                farmer.refresh_from_db()
                api('CREDIT_ANALYST', 'portal_set_credit_decision', {'workflow_revision': farmer.workflow_revision - 1,
                    'decision': 'Approved', 'imab_created': 'Yes', 'customer_no': farmer.customer_no}, args=(farmer.pk,), expected=409)
                api('CREDIT_ANALYST', 'portal_set_credit_decision', {'workflow_revision': farmer.workflow_revision,
                    'decision': 'Approved', 'imab_created': 'Yes', 'customer_no': farmer.customer_no}, args=(farmer.pk,))
                farmer.refresh_from_db()
                api('BUSINESS_ADMIN', 'portal_set_final_decision', {'workflow_revision': farmer.workflow_revision,
                    'final_decision': 'Approved', 'repayment_date': '10', 'repayment_tenor': '6', 'decision_comment': 'Synthetic order approval'}, args=(farmer.pk,))
                preview = api('OPERATIONS_ADMIN', 'portal_requisition_preview', {'farmer_ids': [str(farmer.pk)], 'requisition_date': timezone.localdate().isoformat()})
                generated = api('OPERATIONS_ADMIN', 'portal_requisition_finalize', {'preview_token': preview['preview_token']})
                order = RequisitionBatch.objects.get(pk=generated['batch']['id'])
                from core.services.invoice_parser import official_requisition_eligibility
                farmer.refresh_from_db()
                assert official_requisition_eligibility(farmer)['code'] == 'invoice_order_unsigned'
                record('unsigned_order_blocks_invoice', order=order.order_number)
                (output / f'{order.order_number}.xlsx').write_bytes(bytes(order.file_content))
                assert load_workbook(BytesIO(bytes(order.file_content))).active.cell(9, 2).value == name
                scan = SimpleUploadedFile('synthetic-signed-order.pdf', pdf('SYNTHETIC signed and stamped order\n' + order.order_number), content_type='application/pdf')
                api('BUSINESS_ADMIN', 'portal_document_physical_signoff_upload', {'signed_scan': scan, 'attested_complete': 'true'}, args=('requisition', order.pk), multipart=True)
                assert HomeBiogasAction.objects.filter(farmer=farmer).exists()
                orders.append(order)
                invoice_pdf = pdf(f'HOMEBIOGAS VENTURES LIMITED\nBILL TO\n{name}\n{identity}\n+{phone}\nINVOICE {990001 + len(orders)}\nDATE {timezone.localdate():%d/%m/%Y}\nSUBTOTAL 54,000.00\nDISCOUNT -4,500.00\nTOTAL 49,500.00\nPAYMENT 5,000.00\nBALANCE DUE 44,500.00')
                uploaded = api('OPERATIONS_ADMIN', 'portal_invoice_pool_upload', {
                    'file': SimpleUploadedFile(f'synthetic-invoice-{identity}.pdf', invoice_pdf, content_type='application/pdf')}, multipart=True)
                assert uploaded['auto_matched_count'] == 1, uploaded
                receipts.append(uploaded['receipt_batch'])
                farmer.refresh_from_db()
                assert str(farmer.balance_due) == '44500.00', str(farmer.balance_due)
                record('invoice_parsed_and_matched', farmer_id=str(farmer.pk), invoice=farmer.invoice_number, balance=str(farmer.balance_due))

            farmers = list(JawabuFarmerMaster.objects.order_by('national_id'))
            created = api('OPERATIONS_ADMIN', 'portal_invoice_receipt_batch_payment', {
                'revision': receipts[0]['revision'], 'payment_modes': {str(farmers[0].pk): 'LOAN-JAWABU'}}, args=(receipts[0]['id'],), expected=201)
            batch = PaymentBatch.objects.get(pk=created['batch']['id'])
            api('OPERATIONS_ADMIN', 'portal_payment_batch_cases', {'farmer_ids': [str(farmer.pk) for farmer in farmers],
                'payment_modes': {str(farmers[0].pk): 'LOAN-JAWABU', str(farmers[1].pk): 'CASH'}, 'revision': batch.revision}, args=(batch.pk,))
            batch.refresh_from_db()
            api('OPERATIONS_ADMIN', 'portal_payment_batch_submit', {'revision': batch.revision}, args=(batch.pk,))
            batch.refresh_from_db()
            for farmer in farmers:
                api('OPERATIONS_ADMIN', 'portal_payment_batch_case_review', {'decision': 'approved', 'comment': 'Forbidden synthetic attempt', 'revision': batch.revision}, args=(batch.pk, farmer.pk), expected=403)
                api('BUSINESS_ADMIN', 'portal_payment_batch_case_review', {'decision': 'approved', 'comment': 'Synthetic payment approval', 'revision': batch.revision}, args=(batch.pk, farmer.pk))
                batch.refresh_from_db()
            api('BUSINESS_ADMIN', 'portal_payment_batch_generate', {'revision': batch.revision}, args=(batch.pk,))
            batch.refresh_from_db()
            document = batch.current_document
            (output / 'payment.xlsx').write_bytes(bytes(document.file_content))
            from core.services.payment_documents import payment_template_layout
            workbook = load_workbook(BytesIO(bytes(document.file_content)))
            layout = payment_template_layout(workbook)
            assert workbook[layout.sheet_name].cell(layout.data_start_row, layout.columns['name']).value == identities[1][0]
            api('BUSINESS_ADMIN', 'portal_document_physical_signoff_upload', {'signed_scan': SimpleUploadedFile('synthetic-signed-payment.pdf', pdf('SYNTHETIC signed payment'), content_type='application/pdf'),
                'attested_complete': 'true'}, args=('payment', document.pk), multipart=True)
            batch.refresh_from_db()
            assert batch.status == PaymentBatch.STATUS_COMPLETED, batch.status
            record('payment_completed', number=batch.payment_number, cases=2)
            for farmer in farmers:
                action = HomeBiogasAction.objects.get(farmer=farmer)
                api('HB_STAFF', 'portal_hb_action_transition', {'workstream': 'commissioning', 'commissioning_date': timezone.localdate().isoformat(), 'revision': action.revision}, args=(farmer.pk,), expected=400)
                api('HB_STAFF', 'portal_hb_action_transition', {'workstream': 'installation', 'installation_status': 'installed', 'installation_date': timezone.localdate().isoformat(), 'revision': action.revision}, args=(farmer.pk,))
                action.refresh_from_db()
                api('HB_STAFF', 'portal_hb_action_transition', {'workstream': 'commissioning', 'commissioning_date': (timezone.localdate() - timedelta(days=1)).isoformat(), 'early_commissioning_acknowledged': True, 'revision': action.revision}, args=(farmer.pk,), expected=400)
                api('HB_STAFF', 'portal_hb_action_transition', {'workstream': 'commissioning', 'commissioning_date': timezone.localdate().isoformat(), 'revision': action.revision}, args=(farmer.pk,), expected=400)
                api('HB_STAFF', 'portal_hb_action_transition', {'workstream': 'commissioning', 'commissioning_date': timezone.localdate().isoformat(), 'early_commissioning_acknowledged': True, 'revision': action.revision}, args=(farmer.pk,))
                action.refresh_from_db()
                assert action.commissioning_status == 'commissioned'
                farmer.refresh_from_db()
                record('commissioned', farmer_id=str(farmer.pk), pipeline=current_pipeline_state_label(farmer))
            drain('final_sheet_publication')
            for tab in ('Master Data', 'Eco-conserve'):
                values = sheets[tab].values
                assert len(values) == 2, (tab, len(values))
                assert values[1][values[0].index('Case ID')]
                assert values[1][values[0].index('Current Pipeline State')] == 'COMMISSIONED'
                assert str(values[1][values[0].index('Payment No')]) == '1'
                assert str(values[1][values[0].index('Balance Due')]) in {'44500', '44500.00'}
            from datetime import datetime
            sheet_timestamp = sheets['Master Data'].values[1][sheets['Master Data'].values[0].index('Last Updated At')]
            displayed = datetime.strptime(sheet_timestamp, '%d-%b-%Y %H:%M').replace(tzinfo=timezone.get_current_timezone())
            record('sheet_timestamp_zone_probe', displayed=sheet_timestamp,
                   nairobi_now=timezone.localtime().strftime('%d-%b-%Y %H:%M'),
                   lag_minutes=round((timezone.now() - displayed).total_seconds() / 60))
            assert abs((timezone.now() - displayed).total_seconds()) < 120
            assert all(probe['passes_expected_behavior'] for probe in probe_invoice_phones(output))
            assert not IntegrationOperation.objects.exclude(status=IntegrationOperation.STATUS_SUCCEEDED).exists()
            evidence['status'] = 'passed'
            record('completed', customers=JawabuFarmerMaster.objects.count(), drive_uploads=len(drive_files),
                   publication_statuses=list(IntegrationOperation.objects.values_list('status', flat=True)))
            return 0
    except Exception as exc:
        evidence['status'] = 'failed'
        record('failure', error=str(exc), traceback=traceback.format_exc())
        save_sheets()
        return 1


def probe_invoice_phones(output):
    """Characterize parsing/matching without persisting any invoice or case."""
    from core.models import JawabuFarmerMaster, ParsedInvoice
    from core.services.invoice_parser import parse_invoice_text, _exact_invoice_identity_match
    farmer = JawabuFarmerMaster(customer_name='SYNTHETIC APPLICANT', national_id='99000009', primary_phone='254712345678')
    results = []
    for printed in ('+254712345678', '0712345678', '254712345678', '+254798765432', '254798765432'):
        parsed = parse_invoice_text(f'HOMEBIOGAS VENTURES LIMITED\nBILL TO\nSYNTHETIC APPLICANT\n99000009\n{printed}\nINVOICE 999900\nDATE 26/10/2026\nTOTAL 100.00\nBALANCE DUE 100.00', 1)
        assert parsed is not None
        invoice = ParsedInvoice(customer_name=parsed['customer_name'], customer_id=parsed['customer_id'], customer_phone=parsed['customer_phone'])
        matches = _exact_invoice_identity_match(invoice, farmer)
        expected = '98765432' not in printed
        results.append({'printed_phone': printed, 'parsed_phone': parsed['customer_phone'],
                        'matched': matches, 'expected_match': expected, 'passes_expected_behavior': matches == expected})
    (output / 'invoice-phone-probes.json').write_text(json.dumps(results, indent=2), encoding='utf-8')
    return results
