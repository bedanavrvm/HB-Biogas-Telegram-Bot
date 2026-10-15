"""Admin-configured, document-compatible participant plans for new applications.

Public seam: configure_plan, freeze_plan, workspace. Historical policies never
enter this module. A participant is an individual; a role is only authority.
"""
from copy import deepcopy

from django.core.exceptions import PermissionDenied
from django.db import transaction

from origination.models import LoanOriginationApplication, OriginationSigningParticipant

POLICY = 'all_required'


def enabled(application):
    from origination.services.application_completion import without_signing
    return application.signing_policy_snapshot == POLICY and not without_signing(application)


def candidates(application):
    from origination.services.origination_documents import packet_signers
    return {str(item.get('participant_key') or item['role']): item
            for item in packet_signers(application)}


def default_choices(application):
    available = candidates(application)
    defaults = application.product_definition.signing_defaults or []
    choices = {str(item.get('participant_key') or item.get('role')): dict(item)
               for item in defaults if isinstance(item, dict)}
    return [dict(choices.get(key, {}), participant_key=key,
                 staff_user_id=(application.officer_id if value['role'] == 'officer'
                                else choices.get(key, {}).get('staff_user_id')))
            for key, value in available.items()
            if value.get('required') or any(slot.get('required') for slot in value.get('slots', []))
                or key in choices or (not defaults and value.get('applicable', True))]


def _validate_choices(application, choices):
    from origination.services.loan_origination import OriginationError
    from origination.services.origination_esign import STAFF_SIGNER_ROLES, authorize_staff_signer
    from django.contrib.auth import get_user_model
    available = candidates(application)
    if not isinstance(choices, list) or not choices:
        raise OriginationError('Choose the required signers.')
    keys = [str(item.get('participant_key') or '') for item in choices if isinstance(item, dict)]
    if len(keys) != len(choices) or len(keys) != len(set(keys)) or any(key not in available for key in keys):
        raise OriginationError('Each signer must use a distinct participant defined by the selected documents.')
    if any((value.get('required') or any(slot.get('required') for slot in value.get('slots', []))) and key not in keys for key, value in available.items()):
        raise OriginationError('A required document signer cannot be removed. Choose a compatible document instead.')
    roles = [available[key]['role'] for key in keys]
    if not any(role in {'borrower', 'customer'} for role in roles) or not any(role in STAFF_SIGNER_ROLES for role in roles):
        raise OriginationError('Include an applicant and at least one JBL signer.')
    used_slots, staff_ids = set(), set()
    result = []
    for choice in choices:
        key = str(choice['participant_key'])
        config = deepcopy(available[key])
        role = config['role']
        slots = config.get('slots') or []
        if not any(str(slot.get('type') or 'signature') == 'signature' for slot in slots):
            raise OriginationError('Every participant needs a signature placement in the document editor.')
        for slot in slots:
            identity = (slot.get('document_key', 'primary'), slot['key'])
            if identity in used_slots:
                raise OriginationError('Two people cannot share the same signature placement.')
            used_slots.add(identity)
        staff = None
        if choice.get('staff_user_id'):
            if role not in STAFF_SIGNER_ROLES:
                raise OriginationError('External participants use their mapped identity, not a staff assignment.')
            staff = get_user_model().objects.filter(pk=choice['staff_user_id'], is_active=True).first()
            if not staff:
                raise OriginationError('Choose an active eligible staff member.')
            authorize_staff_signer(actor=staff, application=application, signer_role=role)
            if staff.pk in staff_ids:
                raise OriginationError('Independent JBL participants must be different people.')
            staff_ids.add(staff.pk)
        if role == 'officer' and (not staff or staff.pk != application.officer_id):
            raise OriginationError('The officer signer must be the assigned officer.')
        result.append((key, config, staff))
    return result


@transaction.atomic
def configure_plan(*, application_id, actor, choices, expected_revision,
                   expected_plan_revision, request_id, initializing=False):
    from origination.services.loan_origination import OriginationConflict, OriginationError, _record_event, _require_request_id
    request_id = _require_request_id(request_id)
    if initializing and not (actor and actor.is_active and application_id and str(application_id)):
        raise PermissionDenied('Default initialization requires the assigned officer.')
    if not initializing and not (actor and actor.is_active and actor.is_superuser):
        raise PermissionDenied('Only an active Superuser can configure signing requirements.')
    application = LoanOriginationApplication.objects.select_for_update().get(pk=application_id)
    if initializing and actor.pk != application.officer_id:
        raise PermissionDenied('Only the assigned officer initializes product defaults.')
    if not enabled(application):
        raise OriginationError('This application retains its original approval policy.')
    replay = application.events.filter(action__in=['signing_plan_configured', 'signing_plan_confirmed'], request_id=request_id).first()
    if replay:
        if replay.after_values.get('choices') != choices or replay.actor_id != getattr(actor, 'pk', None):
            raise OriginationError('This request was already used for different signing requirements.')
        return application
    if application.status != 'draft':
        raise OriginationError('Withdraw the application before changing its signers.')
    if application.revision != int(expected_revision) or application.signing_plan_revision != int(expected_plan_revision):
        raise OriginationConflict('The application or signers changed. Refresh before saving.')
    if initializing and application.signing_plan:
        return application
    validated = _validate_choices(application, choices)
    before = application.signing_plan
    existing = {row.participant_key: row.staff_user_id for row in application.signing_participants.filter(
        pk__in=before.get('participants', []))}
    desired = {key: getattr(staff, 'pk', None) for key, config, staff in validated}
    if before and existing == desired:
        _record_event(application, 'signing_plan_confirmed', actor=actor, request_id=request_id,
            after={'choices': choices})
        return application
    ids = []
    for key, config, staff in validated:
        row = OriginationSigningParticipant.objects.create(application=application, role=config['role'],
            participant_key=key, configuration=config, staff_user=staff,
            created_by=actor if not initializing else None)
        ids.append(str(row.pk))
    application.signing_plan_revision += 1
    application.signing_plan = {'version': 1, 'revision': application.signing_plan_revision, 'participants': ids}
    if not initializing:
        application.revision += 1
        application.primary_previewed_revision = None
        application.packet_documents.update(previewed_application_revision=None)
    application.save(update_fields=['signing_plan', 'signing_plan_revision', 'revision', 'primary_previewed_revision', 'updated_at'])
    _record_event(application, 'signing_plan_configured', actor=actor, request_id=request_id,
        before={'plan': before}, after={'plan': application.signing_plan, 'choices': choices})
    return application


def initialize_plan(application):
    if enabled(application) and not application.signing_plan:
        updated = configure_plan(application_id=application.pk, actor=application.officer,
            choices=default_choices(application), expected_revision=application.revision,
            expected_plan_revision=application.signing_plan_revision,
            request_id=f'initial-plan:{application.pk}', initializing=True)
        application.signing_plan = updated.signing_plan
        application.signing_plan_revision = updated.signing_plan_revision


def freeze_plan(application):
    """Resolve live draft values once; package snapshots never resolve them again."""
    from origination.services.loan_origination import OriginationError
    from origination.services.origination_esign import STAFF_SIGNER_ROLES
    available = candidates(application)
    ids = (application.signing_plan or {}).get('participants', [])
    rows = {str(row.pk): row for row in application.signing_participants.filter(pk__in=ids)}
    if not ids or len(rows) != len(ids):
        raise OriginationError('Configure the application signers in Admin before submitting.')
    choices = [{'participant_key': rows[key].participant_key, 'staff_user_id': rows[key].staff_user_id} for key in ids]
    _validate_choices(application, choices)
    result, external_ids = [], set()
    for key in ids:
        row = rows[key]
        config = deepcopy(available[row.participant_key])
        original = row.configuration
        if config.get('slots') != original.get('slots') or config['role'] != row.role:
            raise OriginationError('The selected documents changed. Update the signers in Admin.')
        identity = config.get('identity') or {}
        if row.role in STAFF_SIGNER_ROLES and row.staff_user_id:
            config['identity'] = {**identity, 'name': row.staff_user.get_full_name() or row.staff_user.get_username()}
        if row.role not in STAFF_SIGNER_ROLES:
            national_id = str(identity.get('national_id') or '').strip()
            if national_id and national_id in external_ids:
                raise OriginationError('The same person is listed twice. Use one participant for their document placements.')
            if national_id:
                external_ids.add(national_id)
        result.append({**config, 'participant_id': key, 'staff_user_id': row.staff_user_id, 'required': True,
            'slots': [{**slot, 'required': bool(slot.get('required', True))
                      or slot.get('type', 'signature') in {'signature', 'date_signed'}}
                      for slot in config.get('slots', [])]})
    return result


def successor_plan(application, actor):
    """Copy approved membership on withdrawal without editing submitted records."""
    ids = application.signing_plan.get('participants', [])
    previous = {str(row.pk): row for row in application.signing_participants.filter(pk__in=ids)}
    new_ids = []
    for key in ids:
        old = previous[key]
        row = OriginationSigningParticipant.objects.create(application=application,
            role=old.role, participant_key=old.participant_key, staff_user_id=old.staff_user_id,
            configuration={**deepcopy(old.configuration), 'supersedes_participant_id': key}, created_by=actor)
        new_ids.append(str(row.pk))
    application.signing_plan_revision += 1
    application.signing_plan = {'version':1, 'revision':application.signing_plan_revision, 'participants':new_ids}
    application.save(update_fields=['signing_plan', 'signing_plan_revision', 'updated_at'])


def select_participant(package, *, signer_role='', participant_id=''):
    from origination.services.loan_origination import OriginationError
    configured = (package.context_snapshot or {}).get('_signing_plan', {}).get('policy') == POLICY
    if configured and not participant_id:
        raise OriginationError('Choose the individual signer, not only their role.')
    matching = [item for item in package.participants_snapshot or []
        if (str(item.get('participant_id') or '') == str(participant_id) if participant_id
            else item.get('role') == signer_role)]
    if len(matching) != 1 or (signer_role and matching[0]['role'] != signer_role):
        raise OriginationError('Choose a configured participant from these documents.')
    return matching[0]


def guard_participant(package, participant, actor):
    from origination.services.loan_origination import OriginationError
    from origination.services.origination_esign import authorize_staff_signer
    authorize_staff_signer(actor=actor, application=package.application, signer_role=participant['role'])
    if participant.get('staff_user_id') and participant['staff_user_id'] != actor.pk:
        raise OriginationError('This signature is assigned to another staff member.')
    if participant['role'] == 'officer' and actor.pk != package.application.officer_id:
        raise OriginationError('Only the assigned officer can sign this participant.')
    if participant['role'] != 'officer' and actor.pk == package.application.officer_id and any(
            row['role'] == 'officer' for row in package.participants_snapshot):
        raise OriginationError('Independent JBL participants must be different people.')
    if package.actions.filter(mode='verified', actor=actor, invalidation__isnull=True,
            participant__isnull=False).exclude(participant_id=participant['participant_id']).exists():
        raise OriginationError('Independent JBL participants must be different people.')


def workspace(application, package=None, actor=None):
    if not enabled(application):
        return None
    from origination.services.origination_esign import STAFF_SIGNER_ROLES, esign_enabled
    from origination.services.loan_origination import OriginationError
    if package:
        participants = package.participants_snapshot
        complete = set(package.actions.filter(mode='verified', invalidation__isnull=True).values_list('document_key', 'slot_key'))
    else:
        available = candidates(application)
        participants = [{**available.get(row.participant_key, row.configuration),
            'participant_id': str(row.pk), 'staff_user_id': row.staff_user_id}
            for row in application.signing_participants.filter(pk__in=application.signing_plan.get('participants', []))]
        complete = set()
    rows = []
    for item in participants:
        obligations = [slot for slot in item.get('slots', []) if slot.get('required', item.get('required', True))]
        done = bool(obligations) and all((slot.get('document_key', 'primary'), slot['key']) in complete for slot in obligations)
        can_sign = False
        if actor and package and not package.test_mode and esign_enabled() and application.status in {'signing_pending', 'partially_signed'} and item['role'] in STAFF_SIGNER_ROLES and not done:
            try:
                guard_participant(package, item, actor)
                can_sign = True
            except OriginationError:
                pass
        rows.append({'id': item.get('participant_id'), 'participant_key': item.get('participant_key') or item['role'],
            'role': item['role'], 'name': (item.get('identity') or {}).get('name', ''),
            'staff_user_id': item.get('staff_user_id'), 'staff': item['role'] in STAFF_SIGNER_ROLES,
            'complete': done, 'can_sign': can_sign})
    owns_draft = False
    if actor and actor.pk == application.officer_id:
        from core.services.workflow_access import workflow_access_decision
        from core.services.telegram_identity import user_access
        owns_draft = workflow_access_decision(actor, 'loan_origination', 'origination.create',
            access=user_access(actor, 'loan_origination'), resource=application).allowed
    status_labels = {'draft':'Draft','correction_required':'Changes requested','approved':'Approved',
        'cancelled':'Cancelled','expired':'Expired','declined':'Declined'}
    return {'policy': POLICY, 'revision': application.signing_plan_revision, 'participants': rows,
        'signing_available': esign_enabled(),
        'required_count': len(rows), 'completed_count': sum(row['complete'] for row in rows),
        'status_label': status_labels.get(application.status, 'Awaiting signatures'),
        'can_configure': bool(actor and actor.is_active and actor.is_superuser and application.status == 'draft'),
        'can_submit': bool(owns_draft and application.status == 'draft'),
        'can_recall': bool(owns_draft and application.status in {'signing_pending', 'partially_signed'})}
