"""Revision-bound adoption of published documents before anyone signs.

Publishing never mutates applications. This operation keeps the application,
commercial terms and compatible answers, while retiring unsigned signing work.
The Mini App checks automatically on opening/resuming and before submission;
reads remain read-only and background publication never edits application rows.
"""
from copy import deepcopy

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from origination.models import (
    LoanOriginationApplication, OriginationDocumentTemplate,
    OriginationSigningAction, OriginationSignerSession, OriginationReviewerNotice,
)
from origination.services.origination_documents import _template_snapshot
from origination.services.origination_value_contracts import request_fingerprint


def refresh_block_reason(application):
    """Evidence anywhere in the application's history locks the entire bundle."""
    if application.status in {'cancelled', 'declined', 'expired', 'invalidated'}:
        return 'This application is closed.'
    if application.status in {'partially_signed', 'fully_signed', 'signed_pending_approval', 'approved'}:
        return 'A document has already been signed. Its document version cannot be updated.'
    if (OriginationSigningAction.objects.filter(package__application=application, action_type='signature').exists()
            or OriginationSignerSession.objects.filter(package__application=application).filter(
                Q(verified_at__isnull=False) | Q(status='verified')).exists()
            or application.signing_packages.filter(
                Q(status='fully_signed') | ~Q(signed_document_hash='') | ~Q(final_approved_signed_document_hash='')
            ).exists()):
        return 'A document has already been signed. Its document version cannot be updated.'
    if not application.product_version_id:
        return 'This application is not linked to a product document catalogue.'
    return ''


def _plan(application, *, lock=False):
    from origination.services.loan_origination import OriginationError
    from origination.services.origination_document_catalogue import main_laf_contract, validate_snapshot_combination
    from origination.services.origination_fields import template_form_contract, snapshot_form_schema
    reason = refresh_block_reason(application)
    if reason:
        raise OriginationError(reason)
    documents = list(application.packet_documents.filter(selected=True).order_by('display_order', 'document_key'))
    if not any(row.document_role == 'primary' for row in documents):
        raise OriginationError('This application has no Main LAF to update.')
    rows = []
    for document in documents:
        family = (document.template_snapshot or {}).get('document_type')
        if not family:
            raise OriginationError(f'{document.name} has no document family. Ask an administrator to check it.')
        query = OriginationDocumentTemplate.objects.filter(document_type=family,
            document_role=document.document_role, status='active', published_configuration_revision__isnull=False,
            product_eligibilities__product_id=application.product_version.product_id).select_related(
                'published_configuration_revision', 'product_definition').order_by('pk')
        if lock:
            query = query.select_for_update(of=('self',))
        candidates = list(query)
        if len(candidates) != 1:
            raise OriginationError(f'{document.name} needs exactly one published version available for this product. Ask an administrator to check it.')
        target = candidates[0]
        if target.version < (document.template_snapshot or {}).get('version', 0):
            raise OriginationError(f'{document.name} cannot be replaced by an older version.')
        if document.document_role == 'primary':
            schema, reasons = main_laf_contract(application.product_definition, target)
            if reasons:
                raise OriginationError(' '.join(reasons))
            schema = snapshot_form_schema(schema)
        else:
            schema = deepcopy(template_form_contract(target)[0])
        snapshot = _template_snapshot(target)
        signers = deepcopy(template_form_contract(target)[1])
        changed = (str(document.template_id or '') != str(target.pk)
            or any((document.template_snapshot or {}).get(key) != snapshot.get(key)
                   for key in ('configuration', 'sha256', 'version'))
            or (document.document_role != 'primary' and document.schema_snapshot != schema)
            or document.signer_rules_snapshot != signers)
        rows.append({'document': document, 'target': target, 'schema': schema,
                     'snapshot': snapshot, 'signers': signers, 'changed': changed})
    main = next(row for row in rows if row['document'].document_role == 'primary')
    validate_snapshot_combination(main['schema'], [row['schema'] for row in rows if row is not main])
    token = request_fingerprint([application.revision, [
        [str(row['document'].pk), str(row['target'].pk), row['snapshot'], row['schema'], row['signers']]
        for row in rows]])
    return rows, token


def document_updates(application):
    rows, token = _plan(application)
    new_details = []
    for row in rows:
        old = _fields(row['document'].schema_snapshot)
        for key, field in _fields(row['schema']).items():
            if field.get('source_type', 'user_input') != 'system' and (key not in old or not _same_meaning(old[key], field)):
                label = field.get('label') or key.replace('_', ' ').title()
                if label not in new_details:
                    new_details.append(label)
    return {'revision': application.revision, 'update_token': token, 'updates': [
        {'key': row['document'].document_key, 'name': row['target'].name,
         'from_version': (row['document'].template_snapshot or {}).get('version'),
         'to_version': row['target'].version}
        for row in rows if row['changed']], 'new_details': new_details}


def _fields(schema):
    return {field['key']: field for field in (schema or {}).get('fields', [])
            if isinstance(field, dict) and field.get('key')}


def _same_meaning(old, new):
    def meaning(field):
        return {key: value for key, value in (field.get('value_contract') or {}).items() if key != 'definition'}
    return (old.get('type', 'text') == new.get('type', 'text')
            and old.get('source_type', 'user_input') == new.get('source_type', 'user_input')
            and meaning(old) == meaning(new)
            and (old.get('structure') or {}).get('columns') == (new.get('structure') or {}).get('columns'))


def _retain_answers(payload, old, new):
    """Retain inactive recovery values, but never feed a reused key a new meaning."""
    values = deepcopy(payload or {})
    removed = []
    for key in list(values):
        if key in new and (key not in old or not _same_meaning(old[key], new[key])):
            values.pop(key)
            removed.append(key)
    return values, removed


@transaction.atomic
def auto_refresh_documents(application, *, actor, expected_revision=None):
    """Lazy automatic adoption; no publication work, notifications or paid calls."""
    from origination.services.loan_origination import OriginationError, OriginationConflict
    if not actor or not getattr(actor, 'is_active', False) or actor.pk != application.officer_id:
        return application
    current = LoanOriginationApplication.objects.select_for_update().get(pk=application.pk)
    if refresh_block_reason(current):
        return current
    if expected_revision is not None and current.revision != int(expected_revision):
        raise OriginationConflict('This application changed. Refresh before continuing.')
    try:
        plan = document_updates(current)
        if not plan['updates']:
            return current
        current = refresh_documents(application_id=current.pk, actor=actor, expected_revision=current.revision,
            request_id=f'auto-documents:{current.revision}:{plan["update_token"]}', update_token=plan['update_token'])
        current._document_update_notice = {
            'status': 'updated', 'message': 'Documents updated automatically. Check any new or changed fields.',
            'new_details': plan['new_details'], 'updates': plan['updates']}
    except OriginationError as exc:
        current.refresh_from_db()
        current._document_update_notice = {'status': 'warning',
            'message': f'Your saved application is unchanged. Document updates could not be applied: {exc}'}
    return current


@transaction.atomic
def refresh_documents(*, application_id, actor, expected_revision, request_id, update_token):
    from origination.services.loan_origination import OriginationError, OriginationConflict, _record_event, _require_request_id
    from origination.services.origination_document_choices import reconcile_document_requirements
    from origination.services.origination_signing_plans import reconcile_document_plan, successor_plan
    from origination.services.origination_value_contracts import enabled, packet_contract, person_fields, PERSON_LINKS_KEY, ValueContractError
    request_id = _require_request_id(request_id)
    application = LoanOriginationApplication.objects.select_for_update(of=('self',)).select_related(
        'product_definition', 'product_version').get(pk=application_id)
    if not getattr(actor, 'is_active', False) or application.officer_id != actor.pk:
        raise OriginationError('Only the assigned officer may update these documents.')
    fingerprint = request_fingerprint([expected_revision, update_token])
    replay = application.events.filter(request_id=request_id).first()
    if replay:
        if (replay.action not in {'documents_refreshed', 'documents_refresh_unchanged'}
                or replay.actor_id != actor.pk or replay.metadata.get('refresh_request_sha256') != fingerprint):
            raise OriginationConflict('This request was already used for a different document update.')
        return application
    if int(expected_revision) != application.revision:
        raise OriginationConflict('This application changed. Refresh before updating its documents.')
    # All confirmation paths acquire this application lock before committing a
    # signature. Lock packages too before checking evidence/cancelling sessions.
    packages = list(application.signing_packages.select_for_update().order_by('pk'))
    rows, token = _plan(application, lock=True)
    if not update_token or update_token != token:
        raise OriginationConflict('The published documents changed. Review the update list again.')
    metadata = {'refresh_request_sha256': fingerprint}
    if not any(row['changed'] for row in rows):
        _record_event(application, 'documents_refresh_unchanged', actor=actor, request_id=request_id, metadata=metadata)
        return application
    main = next(row for row in rows if row['document'].document_role == 'primary')
    before = {'status': application.status, 'schema': deepcopy(application.schema_snapshot),
              'signers': deepcopy(application.signer_rules_snapshot), 'form_payload': deepcopy(application.form_payload),
              'documents': [{'key': row['document'].document_key, 'template': deepcopy(row['document'].template_snapshot),
                  'schema': deepcopy(row['document'].schema_snapshot), 'signers': deepcopy(row['document'].signer_rules_snapshot),
                  'values': deepcopy(row['document'].field_payload)} for row in rows]}
    old_fields = _fields(application.schema_snapshot)
    new_fields = _fields(main['schema'])
    for field in application.schema_snapshot.get('application_input_fields', []):
        old_fields[field['key']] = new_fields[field['key']] = field
    previous_signer_keys = set()
    for row in rows:
        previous_signer_keys.update(str(rule.get('participant_key') or rule.get('role'))
            for rule in row['document'].signer_rules_snapshot or [] if isinstance(rule, dict))
        for field in _fields(row['document'].schema_snapshot).values():
            if (field.get('value_contract') or {}).get('scope') == 'application':
                old_fields.setdefault(field['key'], field)
        for field in _fields(row['schema']).values():
            if (field.get('value_contract') or {}).get('scope') == 'application':
                new_fields.setdefault(field['key'], field)
    application.form_payload, cleared = _retain_answers(application.form_payload, old_fields, new_fields)
    for flag in ('acknowledgement_version', 'identity_copy_policy', 'document_completion_version',
                 'application_input_fields', 'commercial_contract_version', 'signer_binding_version'):
        if flag in application.schema_snapshot:
            main['schema'][flag] = application.schema_snapshot[flag]
    main['schema']['form_projection_version'] = 2
    application.schema_snapshot = main['schema']
    application.template_configuration_snapshot = main['snapshot']['configuration']
    application.signer_rules_snapshot = main['signers']
    now = timezone.now()
    for row in rows:
        document = row['document']
        document.field_payload, local_cleared = _retain_answers(document.field_payload,
            _fields(document.schema_snapshot), _fields(row['schema']))
        cleared.extend(f'{document.document_key}.{key}' for key in local_cleared)
        document.template = row['target']
        document.template_snapshot = {**document.template_snapshot, **row['snapshot'], 'resolved_template_id': str(row['target'].pk)}
        document.schema_snapshot, document.signer_rules_snapshot = row['schema'], row['signers']
        document.name = row['target'].name
        document.previewed_application_revision = None
        document.completed_at = None
        document.save(update_fields=['template', 'template_snapshot', 'schema_snapshot', 'signer_rules_snapshot',
            'name', 'field_payload', 'previewed_application_revision', 'completed_at', 'updated_at'])
    application._prefetched_objects_cache = {}
    if enabled(application.schema_snapshot):
        try:
            roles = person_fields(packet_contract(application))
            links = application.form_payload.get(PERSON_LINKS_KEY, {})
            application.form_payload[PERSON_LINKS_KEY] = {target: source for target, source in links.items()
                if len(roles.get(target, {})) == len(roles.get(source, {})) == 3}
            if not links:
                application.form_payload.pop(PERSON_LINKS_KEY, None)
        except ValueContractError as exc:
            raise OriginationError(str(exc), errors=exc.errors) from exc
    notified_reviewers = set()
    for package in packages:
        was_active = package.status not in {'cancelled', 'declined', 'expired'}
        package.signer_sessions.filter(is_active=True).update(is_active=False, status='cancelled', invalidated_at=now, updated_at=now)
        for session in package.signer_sessions.all():
            session.otp_challenges.filter(verified_at__isnull=True, invalidated_at__isnull=True).update(invalidated_at=now)
        if package.status not in {'cancelled', 'declined', 'expired'}:
            package.status = 'cancelled'
            package.save(update_fields=['status', 'updated_at'])
        if was_active and package.reviewed_by_id and package.reviewed_by_id not in notified_reviewers:
            notified_reviewers.add(package.reviewed_by_id)
            OriginationReviewerNotice.objects.create(application=application, package=package, recipient=package.reviewed_by,
                created_by=actor, notice_type=OriginationReviewerNotice.TYPE_APPROVAL_INVALIDATED,
                message='Documents updated before signing. Review the updated application before signing.',
                request_id=f'document-refresh:{request_id}'[:128])
    application.reviewer_notices.filter(notice_type='approval_ready', seen_at__isnull=True).update(seen_at=now)
    application.status = 'draft'
    application.reviewed_by = application.reviewed_at = None
    application.final_reviewed_by = application.final_reviewed_at = None
    application.submitted_at = None
    application.primary_previewed_revision = None
    application.revision += 1
    application.save(update_fields=['status', 'schema_snapshot', 'template_configuration_snapshot', 'signer_rules_snapshot',
        'form_payload', 'reviewed_by', 'reviewed_at', 'final_reviewed_by', 'final_reviewed_at', 'submitted_at',
        'primary_previewed_revision', 'revision', 'updated_at'])
    application.correction_requests.filter(status='open').update(status='addressed', addressed_by=actor, addressed_at=now)
    reconcile_document_requirements(application)
    if packages and application.signing_policy_snapshot == 'all_required':
        successor_plan(application, actor)
    reconcile_document_plan(application, previous_signer_keys)
    _record_event(application, 'documents_refreshed', actor=actor, request_id=request_id, before=before,
        after={'status': 'draft', 'updates': [{'key': row['document'].document_key,
               'template_id': str(row['target'].pk), 'version': row['target'].version} for row in rows],
               'cleared_fields': cleared, 'cancelled_package_ids': [str(package.pk) for package in packages]}, metadata=metadata)
    return application
