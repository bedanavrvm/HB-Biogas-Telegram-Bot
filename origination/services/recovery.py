"""Recovery for an existing document bundle, never a repeat signing action."""
from core.services.miniapp_recovery import issue, page_payload, request_action
from core.services.workflow_access import workflow_access_decision
from origination.models import LoanOriginationApplication, OriginationSigningPackage
from origination.services.origination_access import scope_application_queryset, application_presentation_mode, FULL


def status_payload(actor, access, *, page=1):
    applications = scope_application_queryset(LoanOriginationApplication.objects.all(), user=actor, access=access)
    rows = []
    from django.conf import settings
    from origination.services.origination_signing_configuration import signing_available
    if not signing_available(settings):
        rows.append(issue('signing-configuration', 'Signing delivery', status='Configuration required',
            detail='Applications can be saved. Signing delivery is not available yet.',
            steps=['Ask Origination IT to enable signing and check the configured Africa’s Talking SMS environment, username and API key.',
                   'These are deployment settings, not fields you need to fill in this application.',
                   'After they are repaired, check status and continue with the saved application.']))
    for package in OriginationSigningPackage.objects.filter(application__in=applications,
            application__status='approved', archive_status__in=['failed', 'pending'],
            status=OriginationSigningPackage.STATUS_FULLY_SIGNED).select_related('application').order_by('-updated_at'):
        application = package.application
        if application_presentation_mode(application, user=actor, access=access) != FULL:
            continue
        if not package.signed_document_hash or package.final_approved_signed_document_hash != package.signed_document_hash:
            continue
        capability = ('origination.create' if application.officer_id == actor.pk else 'origination.signing.staff') if application.approval_roles_snapshot or application.signing_policy_snapshot == 'all_required' else 'origination.signing.start'
        action = None
        if package.archive_status == 'failed' and workflow_access_decision(actor, 'loan_origination', capability, access=access, resource=application).allowed:
            action = request_action('Retry saving', f'/api/origination/api/applications/{application.pk}/archive-signed/',
                {'package_id': str(package.pk)}, 'Retry saving this approved document bundle to Drive? Its signatures and approval will not change.')
        rows.append(issue(package.pk, f'{application.reference_number} · Document storage',
            detail='Application is approved. Its signed document bundle is unchanged.',
            status='Waiting' if package.archive_status == 'pending' else 'Needs review', action=action,
            steps=['Ask Origination IT to check Drive access and document storage configuration.',
                   'Retry saving the existing bundle. Do not sign or submit the application again.']))
    return page_payload(rows, page)
