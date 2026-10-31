"""One decision summary for case details and Revisit, without rewriting history."""

STAGES = {'jbl_visit': 'JBL visit', 'credit': 'Credit analysis', 'final': 'Head of Rural review',
          'order': 'Order', 'payment': 'Payment'}


def decision_context(farmer, approvals):
    from core.services.jawabu_pipeline import current_workflow_state
    state = current_workflow_state(farmer)
    if state not in {'rejected', 'deferred'}:
        return None
    outcome = 'Rejected' if state == 'rejected' else 'Deferred'
    stage = farmer.deferred_stage if state == 'deferred' else (
        'final' if farmer.final_decision == 'Rejected' else
        'credit' if farmer.credit_decision == 'Rejected' else
        'jbl_visit' if farmer.jbl_visit_status == 'Rejected by JBL' else '')
    gate = {'final': 'final_review', 'credit': 'credit'}.get(stage)
    approval = approvals.get(gate, {}) if gate else {}
    if not str(approval.get('decision', '')).lower().startswith(outcome.lower()):
        approval = {}
    comment = approval.get('comment') or (
        farmer.final_decision_comment if stage == 'final' else
        farmer.jbl_visit_comment if stage == 'jbl_visit' else '')
    from core.services.jawabu_approvals import REJECTED_REASONS, DEFERRED_REASONS
    event = farmer.pipeline_events.filter(stage_key=gate or stage, action__in=['jbl_visit_completed', 'credit_decision_recorded', 'final_decision_recorded']).order_by('-occurred_at', '-created_at').first()
    facts = event.new_values if event else {}
    if not str(facts.get('decision') or facts.get('status') or '').lower().startswith(outcome.lower()): facts = {}
    reason = approval.get('reason_label') or dict(REJECTED_REASONS + DEFERRED_REASONS).get(facts.get('reason_code'), '')
    comment = comment or facts.get('comment', '')
    from portal_legacy.services import case_payload
    legacy = case_payload(farmer)
    if legacy and legacy['reported_outcome'].startswith(outcome.upper()):
        reason = reason or legacy['reason']; comment = comment or legacy['comment']
    return {'outcome': outcome, 'stage': stage, 'stage_label': STAGES.get(stage, 'Stage not recorded'),
            'reason_label': reason, 'comment': comment or '',
            'recorded_at': farmer.deferred_at.isoformat() if state == 'deferred' and farmer.deferred_at else event.occurred_at.isoformat() if event and facts else None}
