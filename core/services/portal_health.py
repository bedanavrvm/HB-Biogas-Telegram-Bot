"""Read-only operational projections for the Jawabu portal.

Keeping these counts outside the HTTP view makes health checks reusable by the
admin command and future monitoring integrations without coupling them to a
request or exposing external-service credentials.
"""

from __future__ import annotations

from django.utils import timezone


def portal_sync_health(*, now=None, actor=None, access=None) -> dict[str, int]:
    """Return safe counts for stored artifacts that need reconciliation."""
    from core.models import (
        PaymentDocument,
        PaymentDocumentTemplate,
        RequisitionBatch,
        RequisitionTemplate,
    )

    current = now or timezone.now()
    failed_orders = RequisitionBatch.objects.filter(drive_upload_error__gt='')
    failed_payments = PaymentDocument.objects.filter(error__gt='')
    if actor is not None and not actor.is_superuser:
        from core.services.portal_recognition import _scoped_cases
        visible = {str(pk) for pk in _scoped_cases(actor, 'portal.documents.view', access).values_list('pk', flat=True)}
        def owned(queryset):
            ids = [pk for pk, members in queryset.values_list('pk', 'farmer_ids')
                   if members and {str(value) for value in members}.issubset(visible)]
            return queryset.filter(pk__in=ids)
        failed_orders, failed_payments = owned(failed_orders), owned(failed_payments)
    return {
        'failed_order_syncs': failed_orders.count(),
        'failed_payment_syncs': failed_payments.count(),
        'due_order_retries': failed_orders.filter(
            drive_next_retry_at__isnull=True,
        ).count() + failed_orders.filter(drive_next_retry_at__lte=current).count(),
        'due_payment_retries': failed_payments.filter(
            drive_next_retry_at__isnull=True,
        ).count() + failed_payments.filter(drive_next_retry_at__lte=current).count(),
        'requisition_template_ready': int(RequisitionTemplate.objects.filter(is_active=True).exists()),
        'payment_template_ready': int(PaymentDocumentTemplate.objects.filter(is_active=True).exists()),
    }
