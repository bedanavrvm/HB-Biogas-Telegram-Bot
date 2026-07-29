"""Focused coverage for internal history and business-hours SLA projections."""

from datetime import date, datetime
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from core.models import (
    BusinessCalendarHoliday,
    GroupSheetConfiguration,
    JawabuCustomer,
    JawabuCustomerFieldProvenance,
    JawabuFarmerMaster,
    TatTrackerCase,
    WorkflowSlaEscalation,
    WorkflowTimelineAnnotation,
)
from core.services.business_calendar import business_minutes_between
from core.services.jawabu_case360 import record_pipeline_event, serialize_case360
from core.services.tat_tracker import (
    calculated_business_tat_minutes,
    product_by_key,
    stage_business_tat_minutes,
)
from core.services.workflow_sla import (
    WorkflowSlaCandidate,
    collect_tat_daily_metrics,
    escalation_tier,
    record_sla_candidates,
    record_tat_daily_metrics,
)


def nairobi_datetime(year, month, day, hour, minute=0):
    return timezone.make_aware(datetime(year, month, day, hour, minute))


class BusinessCalendarTests(TestCase):
    def test_official_sla_excludes_evenings_and_weekends(self):
        start = nairobi_datetime(2026, 7, 24, 16)  # Friday
        end = nairobi_datetime(2026, 7, 27, 9)  # Monday

        self.assertEqual(business_minutes_between(start, end), Decimal('120.00'))

    def test_active_holiday_is_excluded_from_official_sla(self):
        BusinessCalendarHoliday.objects.create(date=date(2026, 7, 27), name='Test public holiday')
        start = nairobi_datetime(2026, 7, 27, 8)
        end = nairobi_datetime(2026, 7, 28, 9)

        self.assertEqual(business_minutes_between(start, end), Decimal('60.00'))


class UnifiedTimelineTests(TestCase):
    def test_case_history_merges_provenance_and_preserves_redacted_event_shell(self):
        customer = JawabuCustomer.objects.create(national_id='12345678')
        farmer = JawabuFarmerMaster.objects.create(
            customer=customer,
            customer_name='Current Unit',
            national_id='12345678',
            primary_phone='254712345678',
        )
        JawabuFarmerMaster.objects.create(
            customer=customer,
            unit_number=2,
            customer_name='Prior Unit',
            national_id='12345678',
            primary_phone='254712345678',
        )
        event = record_pipeline_event(
            farmer,
            action='jbl_visit_completed',
            stage_key='jbl_visit',
            actor='Field Officer',
            reason='Visit completed.',
        )
        JawabuCustomerFieldProvenance.objects.create(
            farmer=farmer,
            field_name='primary_phone',
            old_value='',
            new_value='254712345678',
            source='system_export',
            source_reference='SYSUP-1',
        )
        WorkflowTimelineAnnotation.objects.create(
            workflow='jawabu_pipeline',
            subject_id=str(farmer.pk),
            source_event_id=f'jawabu:{event.pk}',
            kind='redaction',
            note='Sensitive narrative removed under authorised review.',
        )

        payload = serialize_case360(farmer)
        event_entry = next(entry for entry in payload['timeline'] if entry['action'] == 'jbl_visit_completed')

        self.assertEqual(event_entry['id'], str(event.pk))
        self.assertTrue(event_entry['redacted'])
        self.assertEqual(event_entry['detail'], 'Sensitive event content has been redacted.')
        self.assertTrue(any(entry['kind'] == 'provenance' for entry in payload['timeline']))
        self.assertEqual(payload['related_cases'][0]['unit_number'], 2)


class HybridTatAndEscalationTests(TestCase):
    def setUp(self):
        self.config = GroupSheetConfiguration.objects.create(
            group_id='timeline-tat',
            sheet_id='sheet',
            sheet_name='TRACKER-Business',
            enabled=True,
            workflow={
                'type': 'tat_tracker',
                'products': ['business'],
                'branches': ['Embu'],
                'tat_targets_minutes': {
                    'business': {
                        'total': 240,
                        'stages': {'mpesa_to_admin': 120},
                    },
                },
            },
        )

    def test_tat_exposes_business_hours_without_changing_legacy_wall_clock(self):
        start = nairobi_datetime(2026, 7, 24, 16)  # Friday
        end = nairobi_datetime(2026, 7, 27, 9)  # Monday
        case = TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            case_id='JBL-BS-2026-901',
            product_key='business',
            client_name='Timeline Client',
            branch='Embu',
            stage_values={
                'created': start.isoformat(),
                'mpesa_to_admin': end.isoformat(),
            },
            status='Active',
        )

        self.assertEqual(calculated_business_tat_minutes(case, now=end), Decimal('120.00'))
        self.assertEqual(stage_business_tat_minutes(case, product_by_key('business').stages[0]), Decimal('120.00'))

    def test_escalation_promotes_idempotently_to_management_at_200_percent(self):
        candidate = WorkflowSlaCandidate(
            workflow='tat_tracker',
            subject_id='case-1',
            group_id='timeline-tat',
            stage_key='mpesa_to_admin',
            target_minutes=120,
            overdue_minutes=120,
            branch='Embu',
            responsible_role='BRO',
        )

        records, created = record_sla_candidates([candidate], today=date(2026, 7, 29))
        second_records, second_created = record_sla_candidates([candidate], today=date(2026, 7, 29))
        record = WorkflowSlaEscalation.objects.get(pk=records[0].pk)

        self.assertEqual(created, 1)
        self.assertEqual(second_created, 0)
        self.assertEqual(second_records[0].pk, record.pk)
        self.assertEqual(record.escalation_level, 3)
        self.assertEqual(record.threshold_percent, 200)
        self.assertEqual(record.responsible_role, 'BRO')

    def test_escalation_thresholds_do_not_round_down_for_small_targets(self):
        self.assertEqual(escalation_tier(1, 0)['escalation_level'], 1)
        self.assertEqual(escalation_tier(2, 1)['escalation_level'], 2)
        self.assertEqual(escalation_tier(2, 2)['escalation_level'], 3)

    def test_daily_snapshots_are_idempotent_reporting_projections(self):
        now = timezone.now()
        TatTrackerCase.objects.create(
            group_id=self.config.group_id,
            case_id='JBL-BS-2026-902',
            product_key='business',
            client_name='Snapshot Client',
            branch='Embu',
            bro_name='BRO Snapshot',
            stage_values={'created': (now.replace(hour=8, minute=0, second=0, microsecond=0)).isoformat()},
            status='Active',
        )

        metrics = collect_tat_daily_metrics(metric_date=timezone.localdate(now), now=now)
        records, created = record_tat_daily_metrics(metrics, metric_date=timezone.localdate(now))
        _second_records, second_created = record_tat_daily_metrics(metrics, metric_date=timezone.localdate(now))

        self.assertTrue(records)
        self.assertGreaterEqual(created, 1)
        self.assertEqual(second_created, 0)
        self.assertTrue(any(record.responsible_actor == 'BRO Snapshot' for record in records))
