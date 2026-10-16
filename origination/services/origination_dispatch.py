"""Request-assisted durable Origination notifications and archival, without TAT jobs.

IntegrationOperation owns retries and execution leases. The bounded thread only
wakes persisted work; the next authorized read or the management runner can
resume it after a worker restart. No customer identity is copied into the queue.
"""
import logging
from threading import BoundedSemaphore, Thread

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import close_old_connections, connections, transaction
from django.db.models import Q
from django.utils import timezone

from core.models import AccessGrant, IntegrationOperation
from core.services.external_resilience import execute_operation, reserve_operation
from origination.models import OriginationReviewerNotice, OriginationSigningPackage, OriginationSignerSession

logger = logging.getLogger(__name__)
_slots = BoundedSemaphore(1)
OP_TYPES = ('origination_approval_alert', 'origination_withdrawal_sms', 'origination_approved_archive')


def _reserve(kind, source, actor, *, retry=False):
    is_sms = kind == 'origination_withdrawal_sms'
    integration = source.sms_provider if is_sms else {
        'origination_approval_alert': 'telegram', 'origination_approved_archive': 'google_drive'}[kind]
    from origination.services.origination_sms_delivery import initial_metadata
    operation, _ = reserve_operation(
        integration=integration, operation_type=kind, source_model=source._meta.label,
        source_id=str(source.pk), requested_by=actor, deduplication_key=f'{kind}:{source.pk}',
        max_attempts=1 if is_sms else 5,
        metadata=initial_metadata(integration) if is_sms else None,
    )
    if retry and not is_sms:
        IntegrationOperation.objects.filter(pk=operation.pk, status='dead_letter').update(
            status='pending', attempts=0, next_retry_at=None,
        )
    wake_operations([operation.pk])
    return operation


def queue_archive(package, *, actor=None, retry=False):
    if package.application.status != 'approved' or package.final_approved_signed_document_hash != package.signed_document_hash:
        raise ValueError('Only the approved immutable packet can be archived.')
    if package.archive_status == 'uploaded' and package.final_drive_file_id:
        return _reserve('origination_approved_archive', package, actor)
    package.archive_status = 'pending'
    package.archive_error = ''
    package.save(update_fields=['archive_status', 'archive_error', 'updated_at'])
    return _reserve('origination_approved_archive', package, actor, retry=retry)


def update_approval_notices(package):
    from origination.services.origination_approval import signing_progress
    from origination.services.origination_esign import STAFF_SIGNER_ACCESS_ROLES
    from core.services.workflow_access import workflow_access_decision
    from core.services.telegram_identity import user_access
    application = package.application
    progress = signing_progress(package)
    # Mark only superseded authority steps seen; preserve the currently ready inbox item.
    current_key = f'approval-ready:{package.pk}:{progress["next_approver"]}'
    application.reviewer_notices.filter(package=package, seen_at__isnull=True,
        notice_type='approval_ready').exclude(request_id=current_key if application.status != 'approved' else '').update(seen_at=timezone.now())
    if application.status == 'approved' or not progress['approval_ready']:
        return
    role = progress['next_approver']
    allowed_roles = STAFF_SIGNER_ACCESS_ROLES[role]
    user_ids = AccessGrant.objects.filter(workflow='loan_origination', role__in=allowed_roles).values('user_id')
    signed_actors = package.actions.filter(mode='verified', invalidation__isnull=True, actor__isnull=False).values('actor_id')
    for user in get_user_model().objects.filter(pk__in=user_ids, is_active=True).exclude(pk__in=signed_actors).exclude(pk=application.officer_id):
        decision = workflow_access_decision(user, 'loan_origination', 'origination.signing.staff',
                                            access=user_access(user, 'loan_origination'), resource=application)
        if not decision.allowed or not (decision.technical_override or allowed_roles.intersection(decision.roles)):
            continue
        notice, _ = OriginationReviewerNotice.objects.get_or_create(
            application=application, package=package, recipient=user, request_id=f'approval-ready:{package.pk}:{role}',
            defaults={'created_by': application.officer, 'notice_type': 'approval_ready',
                      'message': 'All preceding signatures are complete. Review the packet, then approve and sign.'},
        )
        _reserve('origination_approval_alert', notice, application.officer)


def queue_withdrawal_notices(package, actor):
    package.reviewer_notices.filter(seen_at__isnull=True).update(seen_at=timezone.now())
    for session in package.signer_sessions.filter(verified_at__isnull=False, is_active=True):
        _reserve('origination_withdrawal_sms', session, actor)


def update_signing_notices(package):
    """Current grants and assignments authorize each individual private task."""
    from origination.services.origination_signing_plans import workspace
    application = package.application
    assigned_ids = [item.get('staff_user_id') for item in package.participants_snapshot if item.get('staff_user_id')]
    users = get_user_model().objects.filter(Q(access_grants__workflow='loan_origination') | Q(pk__in=assigned_ids), is_active=True).distinct()
    for user in users:
        ready = any(row['can_sign'] for row in workspace(application, package, user)['participants'])
        key = f'plan-signing:{package.pk}:{user.pk}'
        if not ready:
            application.reviewer_notices.filter(request_id=key).update(seen_at=timezone.now())
            continue
        notice, _ = OriginationReviewerNotice.objects.get_or_create(application=application, package=package,
            recipient=user, request_id=key, defaults={'created_by': application.officer,
                'notice_type': 'approval_ready', 'message': 'Your signature is needed. Review the documents and sign.'})
        _reserve('origination_approval_alert', notice, application.officer)


def _perform(operation):
    if operation.operation_type == 'origination_approved_archive':
        from origination.services.origination_esign import archive_signed_package
        if not OriginationSigningPackage.objects.filter(pk=operation.source_id).exists():
            return {'cancelled': True}
        try:
            package = archive_signed_package(package_id=operation.source_id, actor=operation.requested_by,
                                             request_id=f'background-archive:{operation.pk}')
        except Exception as exc:
            # Preserve the transport classification hidden by the staff-facing error.
            if exc.__cause__:
                raise exc.__cause__ from exc
            raise
        return {'archive_status': package.archive_status}
    if operation.operation_type == 'origination_withdrawal_sms':
        from origination.services.origination_esign import _send_sms
        session = OriginationSignerSession.objects.select_related('package__application').filter(pk=operation.source_id).first()
        if session is None:
            return {'cancelled': True}
        if session.package.status != 'cancelled':
            return {'cancelled': True}
        from origination.services.origination_sms_delivery import submit_once
        return submit_once(operation, lambda: _send_sms(
            'JBL: signing was withdrawn for changes, not rejected. '
            'The old link and signatures are no longer valid. Please wait for a new signing link.',
            session.phone_normalized, provider=session.sms_provider))
    notice = OriginationReviewerNotice.objects.select_related('recipient', 'application', 'package').filter(pk=operation.source_id).first()
    if notice is None:
        return {'cancelled': True}
    if notice.application.signing_policy_snapshot == 'all_required':
        from origination.services.origination_signing_plans import workspace
        if notice.seen_at or not any(row['can_sign'] for row in workspace(notice.application, notice.package, notice.recipient)['participants']):
            return {'cancelled': True}
        from core.services.telegram_launchers import telegram_api_call
        profile = getattr(notice.recipient, 'staff_profile', None)
        if not profile or not profile.telegram_id:
            raise RuntimeError('Signer Telegram identity is not configured.')
        base = str(getattr(settings, 'APP_BASE_URL', '') or '').rstrip('/')
        telegram_api_call('sendMessage', {'chat_id': profile.telegram_id,
            'text': f'JBL application {notice.application.reference_number}\nYour signature is needed.',
            'reply_markup': {'inline_keyboard': [[{'text': 'Open Origination', 'web_app': {'url': f'{base}/origination/?application={notice.application_id}'}}]]}})
        return {'sent': True}
    from origination.services.origination_approval import signing_progress
    from origination.services.origination_esign import STAFF_SIGNER_ACCESS_ROLES
    from core.services.workflow_access import workflow_access_decision
    from core.services.telegram_identity import user_access
    progress = signing_progress(notice.package)
    decision = workflow_access_decision(notice.recipient, 'loan_origination', 'origination.signing.staff',
                                       access=user_access(notice.recipient, 'loan_origination'), resource=notice.application)
    if (notice.seen_at or notice.package.status not in {'pending', 'in_progress'}
            or not progress['approval_ready'] or not decision.allowed
            or not (decision.technical_override or STAFF_SIGNER_ACCESS_ROLES.get(progress['next_approver'], set()).intersection(decision.roles))):
        return {'cancelled': True}
    from core.services.telegram_launchers import telegram_api_call
    profile = getattr(notice.recipient, 'staff_profile', None)
    if not profile or not profile.telegram_id:
        raise RuntimeError('Approver Telegram identity is not configured.')
    base = str(getattr(settings, 'APP_BASE_URL', '') or '').rstrip('/')
    telegram_api_call('sendMessage', {'chat_id': profile.telegram_id,
        'text': f'JBL application {notice.application.reference_number}\nReady for your approval and signature.',
        'reply_markup': {'inline_keyboard': [[{'text': 'Open Origination', 'web_app': {'url': f'{base}/origination/?application={notice.application_id}'}}]]}})
    return {'sent': True}


def eligible_operations():
    now = timezone.now()
    return IntegrationOperation.objects.filter(operation_type__in=OP_TYPES,
        status__in=['pending', 'retryable_failure', 'running']).filter(Q(next_retry_at__isnull=True) | Q(next_retry_at__lte=now))


def process_operations(operation_ids):
    operations = eligible_operations().filter(pk__in=operation_ids)
    for operation in operations.order_by('created_at')[:5]:
        try:
            execute_operation(operation, lambda op=operation: _perform(op), attempt_budget=1)
        except Exception:
            logger.warning('Origination background operation retained for retry: %s', operation.pk)


def wake_operations(operation_ids):
    ids = tuple(str(pk) for pk in operation_ids)
    def launch():
        if not ids or not _slots.acquire(blocking=False):
            return
        def run():
            close_old_connections()
            try:
                process_operations(ids)
            finally:
                connections.close_all()
                _slots.release()
        try:
            Thread(target=run, daemon=True, name='origination-delivery').start()
        except Exception:
            _slots.release()
            logger.warning('Origination wake-up failed; durable work retained.')
    transaction.on_commit(launch)


def resume_application_work(application):
    package_ids = [str(pk) for pk in application.signing_packages.values_list('pk', flat=True)]
    notice_ids = [str(pk) for pk in application.reviewer_notices.values_list('pk', flat=True)]
    session_ids = [str(pk) for pk in OriginationSignerSession.objects.filter(package_id__in=package_ids).values_list('pk', flat=True)]
    wake_operations(eligible_operations().filter(source_id__in=package_ids + notice_ids + session_ids)
                    .order_by('created_at').values_list('pk', flat=True)[:5])
