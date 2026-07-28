"""Read-only operational projections for the Jawabu portal.

Keeping these counts outside the HTTP view makes health checks reusable by the
admin command and future monitoring integrations without coupling them to a
request or exposing external-service credentials.
"""

from __future__ import annotations

from django.utils import timezone


def portal_sync_health(*, now=None) -> dict[str, int]:
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
