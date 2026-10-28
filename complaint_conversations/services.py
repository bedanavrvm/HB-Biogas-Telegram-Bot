"""Case-scoped staff conversation, separate from HB resolution feedback."""
import hashlib
import json
from uuid import UUID

from django.contrib.auth import get_user_model
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils.dateparse import parse_datetime

from core.models import AccessGrant, CaseUpdate, ComplianceAuditEvent, ParsedMessage
from core.services import complaint_cases as cases
from core.services.compliance_audit import record_event
from .models import CommentContext, CommentMention, CommentReaction

SOURCE = 'browser_staff_comment'
SOURCES = (SOURCE, 'mini_app_comment')
CAPABILITY = 'complaint.conversation.participate'


def accessible_case(group, actor, case_key):
    case = cases._case_queryset(group.group_id, actor=actor).filter(pk=case_key).first()
    if case is None or not cases.actor_can(group, actor, 'complaint.queue.view', case):
        raise PermissionDenied
    return case


def writable_case(group, actor, case_key):
    case = accessible_case(group, actor, case_key)
    if not cases.actor_can(group, actor, CAPABILITY, case):
        raise PermissionDenied
    case = ParsedMessage.objects.select_for_update().get(pk=case.pk)
    if case.complaint_status == 'Closed':
        raise cases.ComplaintCaseError('This complaint is closed. A Manager must reopen it before the conversation can continue.')
    if case.complaint_status == 'Review Needed':
        raise cases.ComplaintCaseError('Complete this complaint’s missing details before continuing the conversation.')
    return case


def eligible_people(group, actor, case, query='', selected=None):
    from core.services.telegram_identity import database_group_configuration
    row = database_group_configuration(group)
    grants = AccessGrant.objects.filter(workflow='complaint_cases', active=True, user__is_active=True).filter(
        Q(group_configuration__isnull=True) | Q(group_configuration=row))
    people = get_user_model().objects.filter(access_grants__in=grants).distinct().order_by('first_name', 'last_name', 'username')
    if selected is not None:
        people = people.filter(pk__in=selected)
    else:
        query = str(query or '').strip()[:100]
        if query:
            people = people.filter(Q(first_name__icontains=query) | Q(last_name__icontains=query) | Q(username__icontains=query))
        people = people[:40]
    result = []
    for person in people:
        try:
            candidate = cases.staff_actor_for_user(group, person)
        except cases.ComplaintCaseError:
            continue
        if cases.actor_can(group, candidate, 'complaint.queue.view', case):
            result.append({'id': str(person.pk), 'label': person.get_full_name() or person.get_username()})
    return result


def comment_target(case, value):
    try:
        key = UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        raise cases.ComplaintCaseError('Choose a comment in this complaint.') from None
    target = CaseUpdate.objects.filter(pk=key, parsed_message=case, source__in=SOURCES).first()
    if target is None:
        raise cases.ComplaintCaseError('That comment is unavailable in this complaint.')
    return target


def serialize(update, actor, evidence_allowed):
    try:
        context = update.conversation_context
    except CommentContext.DoesNotExist:
        context = None
    parent = context.reply_to if context else None
    reactions = list(update.conversation_reactions.all())
    own = next((item for item in reactions if item.actor_reference == str(actor.user.pk)), None)
    return {
        'id': str(update.pk), 'body': update.resolution_text, 'created_at': update.created_at.isoformat(),
        'author': context.author_label if context else update.updated_by or 'Staff member',
        'affiliation': context.affiliation if context else 'HB', 'format': context.text_format if context else 'plain',
        'kind': 'staff_comment' if context else 'hb_feedback',
        'reply_to': None if not parent else {'id': str(parent.pk), 'author': parent.updated_by, 'excerpt': parent.resolution_text[:200]},
        'mentions': [{'id': row.user_reference, 'label': row.label} for row in context.mentions.all()] if context else [],
        'reaction': {'count': sum(item.active for item in reactions), 'active': bool(own and own.active), 'revision': own.revision if own else 0},
        'evidence': [{key: value for key, value in cases.serialize_evidence(item).items()
                      if key != 'preview_url'} for item in update.evidence.all()] if evidence_allowed else [],
    }


def conversation(group, actor, case_key, *, cursor='', focus=''):
    case = accessible_case(group, actor, case_key)
    rows = CaseUpdate.objects.filter(parsed_message=case, source__in=SOURCES).select_related(
        'conversation_context', 'conversation_context__reply_to').prefetch_related(
        'conversation_context__mentions', 'conversation_reactions', 'evidence')
    total = rows.count()
    if focus:
        target = comment_target(case, focus)
        rows = rows.filter(pk=target.pk)
    elif cursor:
        try:
            value = signing.loads(cursor, salt='complaint-conversation-v1', max_age=3600)
            if value['case'] != str(case.pk):
                raise ValueError
            at = parse_datetime(value['at'])
            key = UUID(value['id'])
            if at is None:
                raise ValueError
            rows = rows.filter(Q(created_at__lt=at) | Q(created_at=at, pk__lt=key))
        except (ValueError, TypeError, KeyError, signing.BadSignature):
            raise cases.ComplaintCaseError('Refresh the conversation before loading older comments.', field_errors={'conversation_cursor': 'expired'}) from None
    selected = list(rows.order_by('-created_at', '-pk')[:26])
    more = len(selected) > 25
    selected = selected[:25]
    next_cursor = ''
    if more:
        last = selected[-1]
        next_cursor = signing.dumps({'case': str(case.pk), 'at': last.created_at.isoformat(), 'id': str(last.pk)}, salt='complaint-conversation-v1')
    return {'items': [serialize(row, actor, cases.actor_can(group, actor, 'complaint.case.evidence.view', case)) for row in reversed(selected)],
            'total': total, 'next_cursor': next_cursor,
            'can_post': case.complaint_status not in {'Closed', 'Review Needed'} and cases.actor_can(group, actor, CAPABILITY, case)}


def post_comment(group, actor, case_key, fields, files):
    request_id = cases.create_request_id(fields.get('client_request_id'))
    text = fields.get('body')
    if not isinstance(text, str) or not text.strip() or len(text) > 5000:
        raise cases.ComplaintCaseError('Enter a comment of 5,000 characters or fewer.', field_errors={'body': 'Enter a comment of 5,000 characters or fewer.'})
    text = text.strip()
    try:
        selected = fields.get('mentions') or []
        if isinstance(selected, str):
            selected = json.loads(selected)
        if not isinstance(selected, list) or len(selected) > 10 or any(
            not isinstance(value, str) or not value.isascii() or not value.isdigit()
            or len(value) > 19 or not 0 < int(value) < 2**63 for value in selected):
            raise ValueError
        selected = sorted(set(selected))
    except (ValueError, TypeError):
        raise cases.ComplaintCaseError('Choose up to ten staff mentions from this complaint.') from None
    cases.validate_uploaded_files(files)
    file_facts = []
    for file in files:
        file_facts.append([file.name, hashlib.sha256(file.read()).hexdigest()])
        file.seek(0)
    digest = cases.mutation_payload_hash({'body': text, 'mentions': selected, 'reply_to': str(fields.get('reply_to') or ''), 'files': file_facts, 'actor': str(actor.user.pk)})
    with transaction.atomic():
        case = accessible_case(group, actor, case_key)
        if not cases.actor_can(group, actor, CAPABILITY, case):
            raise PermissionDenied
        case = ParsedMessage.objects.select_for_update().get(pk=case.pk)
        existing = CommentContext.objects.select_related('update').filter(update__parsed_message=case, update__client_request_id=request_id).first()
        if existing:
            if existing.payload_hash != digest:
                raise cases.ComplaintCaseError('This retry identifier belongs to a different comment.')
            update = existing.update
        else:
            case = writable_case(group, actor, case_key)
            if files and not cases.actor_can(group, actor, 'complaint.case.evidence.manage', case):
                raise PermissionDenied
            control = cases.ensure_case_control(case, group)
            try:
                revision = fields.get('expected_revision')
                if isinstance(revision, str) and revision.isascii() and revision.isdigit() and len(revision) <= 19:
                    revision = int(revision)
                if type(revision) is not int or revision < 1:
                    raise ValueError
            except (ValueError, TypeError):
                raise cases.ComplaintCaseError('Refresh this complaint before saving.') from None
            if revision != control.revision:
                raise cases.ComplaintCaseConflict('This complaint changed. Review its latest state; your comment is retained.', current_revision=control.revision)
            if CaseUpdate.objects.filter(parsed_message=case, client_request_id=request_id).exists():
                raise cases.ComplaintCaseError('This retry identifier belongs to another complaint action.')
            parent = comment_target(case, fields['reply_to']) if fields.get('reply_to') else None
            if parent:
                context = CommentContext.objects.filter(update=parent).first()
                if context and context.reply_to_id:
                    parent = context.reply_to
            people = eligible_people(group, actor, case, selected=selected)
            if {person['id'] for person in people} != set(selected):
                raise cases.ComplaintCaseError('One of the selected staff members no longer has access to this complaint.')
            affiliation = 'HB' if 'HB_STAFF' in actor.roles else 'IT' if 'IT' in actor.roles else 'JBL'
            update = CaseUpdate.objects.create(parsed_message=case, group_id=case.group_id, updated_by=actor.name,
                old_status=case.complaint_status, new_status=case.complaint_status, resolution_text=text,
                source=SOURCE, raw_update_text='Browser staff conversation', client_request_id=request_id, sync_status='not_required')
            context = CommentContext.objects.create(update=update, author=actor.user, author_label=actor.name,
                affiliation=affiliation, reply_to=parent, payload_hash=digest)
            CommentMention.objects.bulk_create([CommentMention(comment=context, user_id=person['id'], user_reference=person['id'], label=person['label']) for person in people])
            cases.record_complaint_update(update, case, actor, action='complaint.conversation.commented')
    # Canonical text commits before Drive publication, including on an exact retry.
    if files:
        if not cases.actor_can(group, actor, 'complaint.case.evidence.manage', case):
            raise PermissionDenied
        with transaction.atomic():
            CaseUpdate.objects.select_for_update().get(pk=update.pk)
            cases.store_evidence(group, case, update, actor, files)
    result = conversation(group, actor, case_key)
    result['attachment_failure'] = update.evidence.filter(upload_status__in=('failed', 'pending')).exists()
    return result


def react(group, actor, case_key, update_key, fields):
    request_id = cases.create_request_id(fields.get('client_request_id'))
    if type(fields.get('active')) is not bool or type(fields.get('revision')) is not int or fields['revision'] < 0:
        raise cases.ComplaintCaseError('Refresh the comment before reacting.')
    digest = cases.mutation_payload_hash({'active': fields['active'], 'revision': fields['revision']})
    key = f'complaint-reaction:{actor.user.pk}:{request_id}'
    with transaction.atomic():
        case = accessible_case(group, actor, case_key)
        if not cases.actor_can(group, actor, CAPABILITY, case):
            raise PermissionDenied
        case = ParsedMessage.objects.select_for_update().get(pk=case.pk)
        update = comment_target(case, update_key)
        receipt = ComplianceAuditEvent.objects.filter(deduplication_key=key).first()
        if receipt and (receipt.metadata.get('payload_hash') != digest or receipt.subject_id != str(update.pk)):
            raise cases.ComplaintCaseError('This retry identifier belongs to a different reaction.')
        row, _ = CommentReaction.objects.select_for_update().get_or_create(update=update, actor_reference=str(actor.user.pk), defaults={'actor': actor.user})
        if not receipt:
            writable_case(group, actor, case_key)
            if row.revision != fields['revision']:
                raise cases.ComplaintCaseError('Your reaction changed. Refresh the conversation before trying again.')
            before = {'active': row.active, 'revision': row.revision}
            row.active = fields['active']
            row.revision += 1
            row.save(update_fields=['active', 'revision', 'updated_at'])
            record_event(workflow='complaint_cases', action='complaint.conversation.reacted', subject_type='complaint_comment',
                subject_id=str(update.pk), actor=actor.user, authority_user=actor.user, deduplication_key=key,
                request_id=request_id, source_model='CommentReaction', source_event_id=str(row.pk), before_values=before,
                after_values={'active': row.active, 'revision': row.revision}, metadata={'payload_hash': digest})
    return {'active': row.active, 'revision': row.revision, 'count': update.conversation_reactions.filter(active=True).count()}
