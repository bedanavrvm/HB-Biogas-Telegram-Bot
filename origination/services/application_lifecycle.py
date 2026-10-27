"""Officer-owned removal with durable audit and immutable signed evidence."""
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.models import ComplianceAuditEvent
from core.services.compliance_audit import record_event
from core.services.workflow_access import workflow_access_decision
from origination.models import LoanOriginationApplication, OriginationSigningAction, OriginationSignerSession
from origination.services.loan_origination import OriginationError, OriginationConflict, _require_request_id, _record_event


def has_signature(application):
    return (application.signing_packages.filter(Q(status='fully_signed') | ~Q(signed_document_hash='')
            | ~Q(final_approved_signed_document_hash='')).exists()
        or OriginationSigningAction.objects.filter(package__application=application, action_type='signature').exists()
        or OriginationSignerSession.objects.filter(package__application=application).filter(
            Q(verified_at__isnull=False) | Q(status='verified')).exists()
        or application.status in {'partially_signed', 'fully_signed', 'signed_pending_approval', 'approved', 'invalidated'})


def authorize(application, actor, capability, access=None):
    if access is None:
        from core.services.telegram_identity import user_access
        access = user_access(actor, 'loan_origination')
    decision = workflow_access_decision(actor, 'loan_origination', capability, access=access, resource=application)
    if not decision.allowed or not (decision.technical_override or application.officer_id == actor.pk):
        raise PermissionDenied('Only the assigned officer or scoped Origination IT may remove this application.')


def lifecycle_metadata(application, actor):
    signed = has_signature(application)
    allowed = False
    if actor and application.status != 'invalidated':
        try:
            authorize(application, actor, 'origination.application.invalidate' if signed else 'origination.application.delete')
            allowed = True
        except PermissionDenied:
            pass
    event = application.events.filter(action='application_invalidated').order_by('-occurred_at').first()
    return {'can_delete': allowed and not signed, 'can_invalidate': allowed and signed,
            'invalidation': ({'reason': event.metadata.get('reason', ''),
                              'at': event.occurred_at.isoformat(), 'actor_id': event.actor_id} if event else None)}


@transaction.atomic
def remove_application(*, application_id, actor, expected_revision, request_id, invalidate=False, reason='', access=None):
    request_id = _require_request_id(request_id)
    try:
        application_id = LoanOriginationApplication._meta.pk.to_python(application_id)
    except ValidationError as exc:
        raise OriginationError('Choose a valid application reference.') from exc
    if not isinstance(reason, str):
        raise OriginationError('Enter the reason as text.')
    if not actor or not actor.is_active:
        raise PermissionDenied
    # Stable actor lock also serializes replay after physical deletion.
    get_user_model().objects.select_for_update().get(pk=actor.pk)
    dedup = f'origination-remove:{actor.pk}:{request_id}'
    capability = 'origination.application.invalidate' if invalidate else 'origination.application.delete'
    request = {'application_id': str(application_id), 'revision': int(expected_revision),
               'invalidate': invalidate, 'reason': str(reason or '').strip()}
    prior = ComplianceAuditEvent.objects.filter(deduplication_key=dedup).first()
    if prior:
        if prior.metadata.get('request') != request:
            raise OriginationConflict('This request was used for a different application action.')
        authorize(SimpleNamespace(**prior.metadata['scope']), actor, capability, access)
        return {**prior.after_values, 'replayed': True}
    application = LoanOriginationApplication.objects.select_for_update(of=('self',)).select_related('product_definition').get(pk=application_id)
    authorize(application, actor, capability, access)
    if application.revision != int(expected_revision):
        raise OriginationConflict('This application changed. Refresh before removing it.')
    packages = list(application.signing_packages.order_by('pk').select_for_update().values_list('pk', flat=True))
    signed = has_signature(application)
    if signed != invalidate:
        raise OriginationConflict('This application has signing history. Invalidate it with a reason.' if signed
                                  else 'This application has no signatures. Use Delete application.')
    if invalidate and not 1 <= len(request['reason']) <= 500:
        raise OriginationError('Provide a reason using 1 to 500 characters.')
    if application.status == 'invalidated':
        raise OriginationConflict('This application is already invalidated.')
    scope = {'officer_id': application.officer_id, 'branch': application.branch,
             'product_key': application.product_definition.product_key,
             'group_configuration_id': application.group_configuration_id}
    from core.services.miniapp_deletion import DeletionError, _closure, _delete_rows, _cancel_work
    try:
        rows, retained, unlink, blockers = _closure([application]) if not invalidate else ({}, set(), {}, set())
    except DeletionError as exc:
        raise OriginationError(str(exc)) from exc
    if not invalidate and (retained or unlink or blockers or any(
            label.split('.')[0] != 'origination' or
            (label == application._meta.label and pk != str(application.pk)) for label, pk in rows)):
        raise OriginationError('Linked records outside this application prevent deletion. Ask Origination IT to review them.')
    plan = {'rows': rows, 'deleted': set(rows)}
    if invalidate:
        historical = {}
        from origination.services.origination_signing import render_verified_package, render_test_package
        import hashlib
        for package in application.signing_packages.all().iterator(chunk_size=1):
            if not package.signed_document_hash and package.actions.filter(action_type='signature').exists() and package.frozen_unsigned_document:
                content = render_test_package(package) if package.test_mode else render_verified_package(package)
                package.pending_signed_document = content
                package.save(update_fields=['pending_signed_document', 'updated_at'])
                historical[str(package.pk)] = hashlib.sha256(content).hexdigest()
        keys = {(application._meta.label, str(application.pk))}
        keys.update(('origination.OriginationSigningPackage', str(pk)) for pk in packages)
        keys.update(('origination.OriginationSignerSession', str(pk)) for pk in
                    OriginationSignerSession.objects.filter(package_id__in=packages).values_list('pk', flat=True))
        keys.update(('origination.OriginationReviewerNotice', str(pk)) for pk in
                    application.reviewer_notices.values_list('pk', flat=True))
        _cancel_work({'deleted': keys})
        # Keep final signed bytes and their package status; close only live work.
        application.signing_packages.filter(status__in=['pending', 'in_progress']).update(status='cancelled')
        OriginationSignerSession.objects.filter(package_id__in=packages, is_active=True).update(
            is_active=False, status='cancelled', invalidated_at=timezone.now(), updated_at=timezone.now())
        application.reviewer_notices.filter(seen_at__isnull=True).update(seen_at=timezone.now())
        before = {'status': application.status, 'revision': application.revision}
        application.status = 'invalidated'
        application.revision += 1
        application.save(update_fields=['status', 'revision', 'updated_at'])
        _record_event(application, 'application_invalidated', actor=actor, request_id=request_id,
            before=before, after={'status': 'invalidated'}, metadata={'reason': request['reason'], 'historical_copies': historical})
    else:
        _cancel_work(plan)
        _delete_rows(plan)
    result = {'application_id': str(application_id), 'deleted': not invalidate,
              'status': 'invalidated' if invalidate else 'deleted', 'replayed': False}
    record_event(workflow='loan_origination', action='application.invalidated' if invalidate else 'application.deleted',
        category='workflow', subject_type='loan_origination_application', subject_id=str(application_id),
        actor=actor, authority_user=actor, request_id=request_id, deduplication_key=dedup,
        after_values=result, metadata={'request': request, 'scope': scope}, sensitive=True)
    return result
