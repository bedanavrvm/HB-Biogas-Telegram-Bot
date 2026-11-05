"""Report-only import provenance; never infer origin from missing customer facts."""
from django.db.models import Exists, OuterRef, Q

def report_scope(queryset, workflow, selection=None):
    scope = selection or 'exclude'
    if scope not in {'exclude', 'include'}:
        raise ValueError('Choose whether to include historical imports.')
    if workflow == 'complaints':
        from complaint_legacy.models import ImportRow
        from core.models import ComplaintCaseImportItem
        queryset = queryset.annotate(
            report_imported=Exists(ImportRow.objects.filter(case_id=OuterRef('pk'), committed_at__isnull=False)),
            report_batch_imported=Exists(ComplaintCaseImportItem.objects.filter(parsed_message_id=OuterRef('pk'), status='created')),
        )
        historical = Q(source__in=['complaint_legacy', 'whatsapp_export']) | Q(report_imported=True) | Q(report_batch_imported=True)
    else:
        from portal_legacy.models import LegacyRow
        queryset = queryset.annotate(report_imported=Exists(
            LegacyRow.objects.filter(farmer_id=OuterRef('pk'), committed_at__isnull=False)))
        historical = Q(source='portal_legacy') | Q(report_imported=True)
    return queryset.annotate(report_historical=historical).exclude(historical) if scope == 'exclude' else queryset.annotate(report_historical=historical)


def is_historical(case):
    return bool(getattr(case, 'report_historical', False) or getattr(case, 'source', '') in {'complaint_legacy', 'whatsapp_export', 'portal_legacy'})
