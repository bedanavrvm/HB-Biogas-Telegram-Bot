"""Explicit, bounded reconciliation operations for portal artifacts."""

from __future__ import annotations

from django.db import transaction
from django.utils import timezone

from core.services.document_sync import retry_requisition_batch_upload


def _mark_replaced(document, replacement) -> None:
    """Stop a failed audit row being selected repeatedly by the retry command."""
    summary = dict(document.validation_summary or {})
    summary['reconciliation_note'] = f'Replaced by retry artifact {replacement.id}.'
    # Keep the failed row and its original failure context in the JSON audit
    # snapshot, but clear the active error marker so health/retry queues do not
    # treat an already-reconciled historical row as due forever.
    document.validation_summary = summary
    document.error = ''
    document.drive_next_retry_at = None
    document.save(update_fields=['validation_summary', 'error', 'drive_next_retry_at', 'updated_at'])


def retry_payment_document(document, *, actor: str = 'system:reconcile'):
    """Create one replacement for a failed payment artifact.

    Payment workbooks are immutable snapshots.  Reconciliation therefore
    creates a new version and annotates the failed row instead of overwriting
    it.  A failed final retries through its original HOR review; a failed
    preview/review creates a new review snapshot.
    """
    from core.models import PaymentDocument
    from core.services.payment_documents import approve_payment_document, create_payment_document

    summary = document.validation_summary or {}
    artifact_status = str(summary.get('artifact_status') or '').strip()
    farmer_ids = [str(value) for value in (document.farmer_ids or []) if value]
    if artifact_status == 'final':
        review_id = str(summary.get('review_document_id') or '').strip()
        if not review_id:
            return {'ok': False, 'error': 'Failed final has no linked payment review.', 'document_id': str(document.id)}
        replacement = approve_payment_document(
            review_id,
            actor=actor,
            call_up_comments=document.call_up_comments,
            case_call_up_comments=document.case_call_up_comments or {},
        )
    else:
        replacement = create_payment_document(
            document.order_number,
            payment_number=document.payment_number,
            actor=actor,
            status=artifact_status if artifact_status in {'preview', 'pending_review'} else 'pending_review',
            farmer_ids=farmer_ids or None,
            call_up_comments=document.call_up_comments,
            case_call_up_comments=document.case_call_up_comments or {},
        )
    with transaction.atomic():
        locked = PaymentDocument.objects.select_for_update().get(pk=document.pk)
        _mark_replaced(locked, replacement)
    return {
        'ok': True,
        'document_id': str(document.id),
        'replacement_id': str(replacement.id),
        'status': replacement.status,
    }


def reconcile_due_artifacts(*, kind: str = 'all', limit: int = 25, dry_run: bool = False, actor: str = 'system:reconcile') -> dict:
    """Retry due artifacts with a hard upper bound and optional dry-run."""
    from core.models import PaymentDocument, RequisitionBatch

    current = timezone.now()
    limit = max(1, min(int(limit or 25), 250))
    result = {'dry_run': bool(dry_run), 'orders': [], 'payments': [], 'errors': []}
    if kind in {'all', 'orders'}:
        order_qs = RequisitionBatch.objects.filter(
            drive_upload_error__gt='',
        ).filter(
            drive_next_retry_at__isnull=True,
        ) | RequisitionBatch.objects.filter(
            drive_upload_error__gt='', drive_next_retry_at__lte=current,
        )
        for batch in order_qs.order_by('drive_next_retry_at', 'updated_at')[:limit]:
            entry = {'order_number': batch.order_number, 'attempts': batch.drive_sync_attempts}
            if not dry_run:
                try:
                    retry_result = retry_requisition_batch_upload(batch, actor=actor)
                    entry.update({'ok': bool(retry_result.get('ok')), 'error': retry_result.get('error', '')})
                except Exception as exc:  # pragma: no cover - defensive command boundary
                    entry.update({'ok': False, 'error': str(exc)})
            result['orders'].append(entry)
    if kind in {'all', 'payments'}:
        payment_qs = PaymentDocument.objects.filter(
            status='failed', error__gt='',
        ).filter(
            drive_next_retry_at__isnull=True,
        ) | PaymentDocument.objects.filter(
            status='failed', error__gt='', drive_next_retry_at__lte=current,
        )
        for document in payment_qs.order_by('drive_next_retry_at', 'updated_at')[:limit]:
            entry = {
                'document_id': str(document.id),
                'order_number': document.order_number,
                'payment_number': document.payment_number,
                'attempts': document.drive_sync_attempts,
            }
            if not dry_run:
                try:
                    entry.update(retry_payment_document(document, actor=actor))
                except Exception as exc:  # pragma: no cover - defensive command boundary
                    entry.update({'ok': False, 'error': str(exc)})
            result['payments'].append(entry)
    return result
