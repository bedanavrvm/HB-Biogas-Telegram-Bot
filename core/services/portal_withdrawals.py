"""Client withdrawal pauses the same case without creating a deferral deadline."""

from django.db import transaction

from core.models import JawabuFarmerMaster
from core.services.jawabu_pipeline import _advance_state, _clear_deferral, current_workflow_state
from core.services.workflow_transitions import validate_workflow_revision


STAGES = {
    'jbl_visit': ('JBL Visit', 'portal.jbl_visit.write'),
    'credit': ('Credit Analysis', 'portal.credit.write'),
    'final_review': ('Head of Rural Review', 'portal.final_review.write'),
    'order': ('Order Preparation', 'portal.requisition.write'),
}


def withdrawal_stage(farmer):
    state = current_workflow_state(farmer)
    if state == 'withdrawn':
        return farmer.withdrawn_stage
    if state == 'deferred':
        return {'final': 'final_review'}.get(farmer.deferred_stage, farmer.deferred_stage)
    return state if state in STAGES else ''


@transaction.atomic
def change_withdrawal(farmer, *, action, reason, expected_revision, request_id, actor, stage):
    from core.services.jawabu_case360 import record_pipeline_event
    from core.services.jawabu_comments import record_case_comment
    from core.services.portal_publication import reserve_farmer_publication
    from hb_operations.models import HomeBiogasAction
    from payments.models import PaymentBatchCase
    from requisitions.services import order_for_farmer

    farmer = JawabuFarmerMaster.objects.select_for_update().get(pk=farmer.pk)
    reason = str(reason or '').strip()
    if action not in {'withdraw', 'resume'} or not reason or len(reason) > 4000:
        raise ValueError('Choose withdraw or resume and enter a note of 1–4000 characters.')
    if not request_id:
        raise ValueError('A request key is required.')
    event_action = 'case_withdrawn' if action == 'withdraw' else 'withdrawal_resumed'
    replay = farmer.pipeline_events.filter(request_id=request_id).first()
    if replay:
        if replay.action != event_action or replay.reason != reason or replay.actor_user_id != actor.pk:
            raise ValueError('This request key was used for another action. Refresh and try again.')
        return farmer
    validate_workflow_revision(farmer, expected_revision)
    if farmer.status != 'active':
        raise ValueError('Only active Portal cases can be withdrawn or resumed.')
    state = current_workflow_state(farmer)
    if stage not in STAGES or withdrawal_stage(farmer) != stage:
        raise ValueError('The responsible stage changed. Refresh this case.')
    if (action == 'withdraw' and state == 'withdrawn') or (action == 'resume' and state != 'withdrawn'):
        raise ValueError('This action is not available in the current case state.')
    order = order_for_farmer(farmer)
    if farmer.order_number or farmer.requisition_batch_id or order:
        raise ValueError('Release this case through the unsigned order controls first. Signed orders cannot be withdrawn.')
    if farmer.invoice_number or PaymentBatchCase.objects.filter(farmer=farmer).exists() or HomeBiogasAction.objects.filter(farmer=farmer).exists():
        raise ValueError('This case has financial or fulfilment evidence. Use the controlled correction process.')
    # A withdrawal replaces an existing hold; it must not inherit its expiry.
    _clear_deferral(farmer, actor.get_username(), request_id)
    prior_next_visit = farmer.jbl_next_visit_date
    farmer.jbl_next_visit_date = None
    farmer.withdrawn_stage = stage if action == 'withdraw' else ''
    resumed_fields = []
    if action == 'resume':
        field = {'jbl_visit': 'jbl_visit_status', 'credit': 'credit_decision', 'final_review': 'final_decision'}.get(stage)
        if field and getattr(farmer, field) == 'Deferred / On Hold':
            # The old hold remains in audit; its current decision must allow the queue to resume.
            setattr(farmer, field, 'JBL to Schedule Visit' if stage == 'jbl_visit' else '')
            resumed_fields.append(field)
    target = 'withdrawn' if action == 'withdraw' else stage
    before, revision_before, revision_after = _advance_state(farmer, target, before_state=state)
    farmer.save(update_fields=['withdrawn_stage', 'workflow_state', 'workflow_state_entered_at',
                               'workflow_revision', 'deferred_at', 'deferred_stage', 'deferred_until', 'jbl_next_visit_date', 'updated_at', *resumed_fields])
    event = record_pipeline_event(
        farmer, action=event_action, stage_key=stage, actor=actor.get_username(), actor_user=actor,
        request_id=request_id, reason=reason, from_state=before, to_state=target,
        transition_code=f'jawabu.{event_action}', revision_before=revision_before, revision_after=revision_after,
        old_values={'workflow_state': before, 'next_visit_date': prior_next_visit.isoformat() if prior_next_visit else None}, new_values={'workflow_state': target, 'withdrawn_stage': farmer.withdrawn_stage, 'next_visit_date': None},
    )
    record_case_comment(farmer=farmer, stage_key=stage, comment=reason, actor=actor.get_username(),
                        actor_user=actor, request_id=request_id, pipeline_event=event, occurred_at=event.occurred_at)
    reserve_farmer_publication(farmer, request_id=request_id, requested_by=actor)
    return farmer
