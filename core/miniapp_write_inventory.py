"""Executable inventory of every Telegram Mini App unsafe-method route.

The CI checker resolves URL methods from source and requires each discovered
route to appear here or in the explicit non-Mini-App exclusion register.
Entries intentionally describe both transport and domain replay boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WriteRoutePolicy:
    methods: tuple[str, ...]
    authentication: str
    capability: str
    scope: str
    request_key_binding: str
    domain_replay: str


WRITE_ROUTE_INVENTORY: dict[str, WriteRoutePolicy] = {}


def _add(
    names: str,
    *,
    methods: tuple[str, ...] = ('POST',),
    authentication: str,
    capability: str,
    scope: str,
    request_key_binding: str,
    domain_replay: str,
) -> None:
    for name in names.split():
        if name in WRITE_ROUTE_INVENTORY:
            raise RuntimeError(f'Duplicate Mini App write-route inventory entry: {name}')
        WRITE_ROUTE_INVENTORY[name] = WriteRoutePolicy(
            methods=methods,
            authentication=authentication,
            capability=capability,
            scope=scope,
            request_key_binding=request_key_binding,
            domain_replay=domain_replay,
        )


_add(
    'staff_telegram_activation_submit',
    authentication='Canonical Telegram initData plus single-use activation proof',
    capability='Enrolled staff activation only',
    scope='One inactive Telegram binding challenge for the canonical Django user',
    request_key_binding='miniapp_idempotency_boundary',
    domain_replay='Single-use activation consumption and immutable Telegram-ID uniqueness',
)
_add(
    'telegram_session_login',
    authentication='Canonical Telegram initData',
    capability='At least one resolved workflow AccessGrant (returned, not inferred)',
    scope='Canonical active Django user',
    request_key_binding='miniapp_idempotency_boundary',
    domain_replay='Django session rotation; repeated login does not create workflow state',
)
_add(
    'miniapp_diagnostic_session_start miniapp_diagnostic_signals',
    authentication='Canonical Telegram initData/AccessGrant, then signed diagnostic session token',
    capability='Workflow AccessGrant for the declared Mini App surface',
    scope='Actor-owned diagnostic session UUID',
    request_key_binding='miniapp_idempotency_boundary',
    domain_replay='Unique session UUID and unique session/event UUID constraints',
)
_add(
    'jawabu_farmers_review_commit fca_review_commit',
    authentication='Canonical Telegram identity plus signed batch review token',
    capability='Batch review-token commit authority',
    scope='Exact staged batch and its uncommitted rows',
    request_key_binding='miniapp_write_response',
    domain_replay='Row commit state, source-row identity, and Sheet operation deduplication',
)
_add(
    'miniapp_draft',
    methods=('DELETE', 'POST'),
    authentication='Canonical Telegram identity plus workflow context token/grant',
    capability='Workflow-specific draft ownership',
    scope='Canonical user + workflow + context key',
    request_key_binding='miniapp_write_response',
    domain_replay='Unique owner/context draft plus optimistic draft revision',
)


_ORIGINATION_AUTH = 'Canonical Telegram identity through portal_auth_required'
_ORIGINATION_SCOPE = 'Origination AccessGrant capability plus application branch/ownership scope'
_ORIGINATION_KEY = 'portal_auth_required -> canonical request identity'
_ORIGINATION_REPLAY = 'Request-keyed append-only event plus application revision/state constraints'

_add(
    'loan_origination_applications',
    authentication=_ORIGINATION_AUTH,
    capability='portal.origination.create',
    scope='Authorized branch and active product availability',
    request_key_binding=_ORIGINATION_KEY,
    domain_replay='Application create request key and product/schema snapshot uniqueness',
)
_add(
    'loan_origination_application_detail',
    methods=('PATCH',), authentication=_ORIGINATION_AUTH,
    capability='portal.origination.create', scope=_ORIGINATION_SCOPE,
    request_key_binding=_ORIGINATION_KEY,
    domain_replay='Draft request key plus optimistic application revision and payload conflict check',
)
_add(
    'loan_origination_quote_preview loan_origination_submit loan_origination_confirm_signing '
    'loan_origination_recall loan_origination_document_selection loan_origination_document_fields',
    authentication=_ORIGINATION_AUTH,
    capability='portal.origination.create', scope=_ORIGINATION_SCOPE,
    request_key_binding=_ORIGINATION_KEY, domain_replay=_ORIGINATION_REPLAY,
)
_add(
    'loan_origination_preview loan_origination_document_preview '
    'loan_origination_packet_preview loan_origination_review_packet_preview',
    authentication=_ORIGINATION_AUTH,
    capability='portal.origination.view', scope=_ORIGINATION_SCOPE,
    request_key_binding=_ORIGINATION_KEY,
    domain_replay='Revision-bound deterministic render and request-keyed preview event',
)
_add(
    'loan_origination_review loan_origination_final_review '
    'loan_origination_correction_takeover loan_origination_reviewer_notice_seen',
    authentication=_ORIGINATION_AUTH,
    capability='portal.origination.review', scope=_ORIGINATION_SCOPE,
    request_key_binding=_ORIGINATION_KEY, domain_replay=_ORIGINATION_REPLAY,
)
_add(
    'loan_origination_prepare_review_packet loan_origination_prepare_signing '
    'loan_origination_signer_sessions loan_origination_reset_signer_session '
    'loan_origination_production_stamp loan_origination_archive_signed '
    'loan_origination_signing_requirements loan_origination_test_signing_action '
    'loan_origination_test_signing_preview',
    authentication=_ORIGINATION_AUTH,
    capability='portal.origination.signing.start', scope=_ORIGINATION_SCOPE,
    request_key_binding=_ORIGINATION_KEY,
    domain_replay='Request-key uniqueness plus immutable package/session/document hashes',
)
_add(
    'loan_origination_staff_signature',
    authentication=_ORIGINATION_AUTH,
    capability='portal.origination.signing.staff', scope=_ORIGINATION_SCOPE,
    request_key_binding=_ORIGINATION_KEY,
    domain_replay='Signer-slot/request uniqueness plus exact packet hash binding',
)
_add(
    'loan_origination_evidence_upload loan_origination_evidence_remove',
    authentication=_ORIGINATION_AUTH,
    capability='portal.origination.create or portal.origination.signing.start',
    scope='Application, requirement, actor, branch, and evidence ownership',
    request_key_binding=_ORIGINATION_KEY,
    domain_replay='Request key, evidence slot/count constraints, file hash, and durable Drive operation',
)


_add(
    'spin_form_submit',
    authentication='Canonical Telegram initData or scoped signed submission token',
    capability='spin.request.create',
    scope='Configured SPIN group plus AccessGrant branch/product scope',
    request_key_binding='miniapp_write_response',
    domain_replay='Unique client request key and SPIN request sequence/content checks',
)
_add(
    'spin_form_settings spin_form_settings_personal',
    authentication='Canonical Telegram initData', capability='spin.request.view',
    scope='Canonical user and configured SPIN group',
    request_key_binding='miniapp_write_response',
    domain_replay='User/workflow preference uniqueness; settings proposal revision where applicable',
)
_add(
    'spin_form_review_update', methods=('PATCH', 'POST'),
    authentication='Canonical Telegram initData', capability='spin.request.review',
    scope='SPIN AccessGrant plus group/branch/product/resource scope',
    request_key_binding='miniapp_write_response',
    domain_replay='Request-keyed review event plus row state/revision constraints',
)
_add(
    'spin_batch_review_resolve',
    authentication='Canonical Telegram initData', capability='spin.batch.review',
    scope='SPIN AccessGrant plus group and batch-item scope',
    request_key_binding='miniapp_write_response',
    domain_replay='Unique batch review item/action request and terminal state checks',
)
_add(
    'spin_form_complete',
    authentication='Canonical Telegram initData', capability='spin.request.complete',
    scope='SPIN AccessGrant plus group/branch/product/resource scope',
    request_key_binding='miniapp_write_response',
    domain_replay='Request-keyed completion, terminal-state guard, media uniqueness, durable external operation',
)


_add(
    'tat_tracker_bootstrap tat_tracker_home tat_tracker_home_fragment tat_tracker_settings '
    'tat_tracker_settings_personal tat_tracker_tasks tat_tracker_connect_private_alerts '
    'tat_tracker_disconnect_private_alerts tat_tracker_detail tat_tracker_update',
    authentication='Canonical Telegram initData or scoped signed TAT launcher token',
    capability='tat.home.view (write actions apply their stage capability in the service)',
    scope='TAT AccessGrant plus configured group, branch, role, and case scope',
    request_key_binding='miniapp_write_response',
    domain_replay='Read-only POST or request-keyed preference/connection/stage event with revision checks',
)
_add(
    'tat_tracker_search tat_tracker_search_fragment',
    authentication='Canonical Telegram initData', capability='tat.case.search',
    scope='TAT AccessGrant plus configured group and queue visibility',
    request_key_binding='miniapp_write_response',
    domain_replay='Read-only POST; no canonical workflow mutation',
)
_add(
    'tat_tracker_target_settings',
    authentication='Canonical Telegram initData', capability='tat.settings.targets.propose',
    scope='TAT configuration authority and exact group/version',
    request_key_binding='miniapp_write_response',
    domain_replay='Proposal request key plus configuration revision',
)
_add(
    'tat_tracker_settings_request tat_tracker_settings_review',
    authentication='Canonical Telegram initData', capability='TAT settings maker/checker capability',
    scope='Canonical user, proposal, and configured group',
    request_key_binding='miniapp_write_response',
    domain_replay='Proposal/review request uniqueness plus optimistic revision and terminal status',
)
_add(
    'tat_tracker_create tat_tracker_identity_context',
    authentication='Canonical Telegram initData', capability='tat.case.create',
    scope='TAT AccessGrant plus configured group/branch/product creation scope',
    request_key_binding='miniapp_write_response',
    domain_replay='Unique create_request_id plus case identifier and workflow-mode constraints',
)
_add(
    'tat_tracker_task_resolve',
    authentication='Canonical Telegram initData', capability='Recipient task access',
    scope='Opaque task locator, current recipient, group, and active assignment',
    request_key_binding='miniapp_write_response',
    domain_replay='Idempotent read receipt/task locator state transition',
)


_COMPLAINT_AUTH = 'Canonical Telegram initData resolved to an active Django user'
_COMPLAINT_SCOPE = 'Complaint AccessGrant plus configured group and case scope'
_add(
    'complaint_cases_bootstrap complaint_cases_list complaint_cases_list_fragment complaint_cases_detail',
    authentication=_COMPLAINT_AUTH,
    capability='complaint.queue.view / complaint.case.source.view', scope=_COMPLAINT_SCOPE,
    request_key_binding='complaint miniapp_write_response',
    domain_replay='Read-only POST; no canonical workflow mutation',
)
_add(
    'complaint_cases_settings_personal',
    authentication=_COMPLAINT_AUTH, capability='complaint.queue.view',
    scope='Canonical user preference', request_key_binding='complaint miniapp_write_response',
    domain_replay='Unique user/workflow preference row',
)
_add(
    'complaint_cases_create',
    authentication=_COMPLAINT_AUTH, capability='complaint.case.create', scope=_COMPLAINT_SCOPE,
    request_key_binding='complaint miniapp_write_response',
    domain_replay='Unique create request plus source/content deduplication and media content hashes',
)
_add(
    'complaint_cases_update',
    authentication=_COMPLAINT_AUTH, capability='complaint.case.update', scope=_COMPLAINT_SCOPE,
    request_key_binding='complaint miniapp_write_response',
    domain_replay='Unique update request, expected case revision, and evidence content hash',
)
_add(
    'complaint_cases_resolve complaint_cases_reopen',
    authentication=_COMPLAINT_AUTH, capability='complaint.case.close / complaint.case.reopen',
    scope=_COMPLAINT_SCOPE, request_key_binding='complaint miniapp_write_response',
    domain_replay='Unique transition request plus expected revision and legal state transition',
)
_add(
    'complaint_cases_sync_retry',
    authentication=_COMPLAINT_AUTH, capability='complaint.case.sync.retry', scope=_COMPLAINT_SCOPE,
    request_key_binding='complaint miniapp_write_response',
    domain_replay='Existing case/update operation retry; durable external-operation deduplication',
)
_add(
    'complaint_cases_evidence_access',
    authentication=_COMPLAINT_AUTH, capability='complaint.case.evidence.view', scope=_COMPLAINT_SCOPE,
    request_key_binding='complaint miniapp_write_response',
    domain_replay='Read/audit access keyed by evidence and actor; no duplicate media write',
)


_add(
    'order_approval_webapp_submit',
    authentication='Canonical Telegram initData or scoped signed order form token',
    capability='Authorized order launcher submission',
    scope='Configured order group and exact matched row/edit fingerprint',
    request_key_binding='miniapp_write_response',
    domain_replay='Request key, row fingerprint, media content hash, and Sheet operation deduplication',
)
_add(
    'order_approval_webapp_lookup order_approval_webapp_suggest',
    authentication='Canonical Telegram initData or scoped signed order form token',
    capability='Authorized order launcher lookup', scope='Configured order group',
    request_key_binding='miniapp_write_response',
    domain_replay='Read-only POST; no canonical workflow mutation',
)


_PORTAL_AUTH = 'Canonical Telegram initData through portal_auth_required'
_PORTAL_SCOPE = 'Portal AccessGrant plus branch/product/resource scope decision'
_PORTAL_KEY = 'portal_auth_required -> canonical request identity'
_PORTAL_REPLAY = 'Request-keyed domain event plus workflow revision/state/database constraints'

_add(
    'portal_settings', authentication=_PORTAL_AUTH,
    capability='Operation-specific setting capability from the server catalogue', scope='Canonical user',
    request_key_binding=_PORTAL_KEY, domain_replay='Unique preference/proposal row plus revision',
)
_add(
    'portal_approval_delegations portal_approval_delegation_revoke',
    authentication=_PORTAL_AUTH, capability='portal.approval.delegation.authorize',
    scope='Delegator capability, branch/product bounds, delegate and expiry',
    request_key_binding=_PORTAL_KEY, domain_replay='Request-keyed delegation plus overlap/revocation constraints',
)
_add(
    'portal_workspace_views portal_workspace_view_detail portal_workspace_view_activate '
    'portal_workspace_view_startup portal_workspace_case_pin portal_workspace_case_unpin '
    'portal_workspace_recents_clear',
    methods=('DELETE', 'PATCH', 'POST'), authentication=_PORTAL_AUTH,
    capability='portal.workspace.manage', scope='Canonical user-owned workspace and in-scope case',
    request_key_binding=_PORTAL_KEY, domain_replay='User/object uniqueness plus optimistic revision or idempotent set/delete',
)
_add(
    'portal_import_stage portal_import_archive_attempt portal_import_archive',
    authentication=_PORTAL_AUTH, capability='portal.imports.view (IT-only policy)',
    scope='IT actor, import kind, staged batch, and restricted archive',
    request_key_binding=_PORTAL_KEY,
    domain_replay='Mandatory request key, upload hash/batch status, and durable archive operation',
)
_add(
    'portal_report_preview portal_reports portal_report_detail portal_report_archive',
    authentication=_PORTAL_AUTH, capability='portal.reports.manage',
    scope='IT-only report owner and catalogue-constrained definition', request_key_binding=_PORTAL_KEY,
    domain_replay='Request-keyed definition/audit event plus report revision/archive state',
)
_add(
    'portal_report_run portal_report_export',
    authentication=_PORTAL_AUTH, capability='portal.reports.view',
    scope='IT-only report and canonical scoped Portal cases', request_key_binding=_PORTAL_KEY,
    domain_replay='Request-keyed audit/export operation; constrained read result',
)
_add(
    'portal_set_maintenance', authentication=_PORTAL_AUTH,
    capability='portal.health.maintenance.manage', scope='IT-controlled global Portal maintenance state',
    request_key_binding=_PORTAL_KEY, domain_replay='Request-keyed maintenance event plus state revision',
)
_add(
    'portal_log_jbl_visit portal_complete_jbl_visit', authentication=_PORTAL_AUTH,
    capability='portal.jbl_visit.write', scope=_PORTAL_SCOPE,
    request_key_binding=_PORTAL_KEY,
    domain_replay='Visit request key, expected workflow revision, media hashes, and external-operation register',
)
_add(
    'portal_jbl_visit_draft portal_credit_decision_draft portal_final_review_draft',
    methods=('DELETE', 'POST'), authentication=_PORTAL_AUTH,
    capability='Stage-specific write capability', scope='Canonical user + case + draft workflow',
    request_key_binding=_PORTAL_KEY, domain_replay='Unique user/case draft plus optimistic draft revision',
)
_add(
    'portal_voice_transcription portal_voice_transcription_cancel',
    authentication=_PORTAL_AUTH, capability='portal.jbl_visit.write', scope=_PORTAL_SCOPE,
    request_key_binding=_PORTAL_KEY,
    domain_replay='Request-keyed attempt, bounded quota, retry-attempt identity, and terminal cancellation',
)
_add(
    'portal_publication_attempt', authentication=_PORTAL_AUTH,
    capability='portal.publication.retry', scope='Authorized actor plus existing operation/source case',
    request_key_binding=_PORTAL_KEY, domain_replay='Durable IntegrationOperation deduplication and attempt lease',
)
_add(
    'portal_upload_jbl_media', authentication=_PORTAL_AUTH,
    capability='portal.jbl_media.write', scope=_PORTAL_SCOPE,
    request_key_binding=_PORTAL_KEY,
    domain_replay='Request key, file count/size, content hash, attachment uniqueness, durable Drive operation',
)
_add(
    'portal_clear_approval_condition', authentication=_PORTAL_AUTH,
    capability='Condition-owning approval capability', scope='Condition, case, branch, product, and delegation',
    request_key_binding=_PORTAL_KEY, domain_replay='Request-keyed append-only condition event and terminal clear state',
)
_add(
    'portal_set_credit_decision', authentication=_PORTAL_AUTH,
    capability='portal.credit_decision.write', scope=_PORTAL_SCOPE,
    request_key_binding=_PORTAL_KEY, domain_replay=_PORTAL_REPLAY,
)
_add(
    'portal_set_final_decision portal_return_for_rework', authentication=_PORTAL_AUTH,
    capability='portal.final_decision.write / stage-specific rework capability', scope=_PORTAL_SCOPE,
    request_key_binding=_PORTAL_KEY, domain_replay=_PORTAL_REPLAY,
)
_add(
    'portal_requisition_preview portal_requisition_workbook_preview portal_requisition_generate '
    'portal_assign_order portal_requisition_batch_retry_sync',
    authentication=_PORTAL_AUTH, capability='portal.requisition.write', scope=_PORTAL_SCOPE,
    request_key_binding=_PORTAL_KEY,
    domain_replay='Order/batch request uniqueness, revision, document hash/version, and external operation',
)
_add(
    'portal_upload_batch_invoices portal_invoice_pool_upload portal_invoice_batch_confirm '
    'portal_invoice_bulk_action portal_invoice_draft_edit portal_invoice_match '
    'portal_invoice_unmatch portal_invoice_ignore portal_invoice_restore',
    methods=('PATCH', 'POST'), authentication=_PORTAL_AUTH,
    capability='portal.invoice.write', scope=_PORTAL_SCOPE,
    request_key_binding=_PORTAL_KEY,
    domain_replay='Upload/batch/invoice request key, content hash, revision/status, and match uniqueness',
)
_add(
    'portal_invoice_identity_review portal_invoice_name_change_create '
    'portal_invoice_name_change_batches portal_invoice_name_change_close '
    'portal_invoice_name_change_follow_up portal_invoice_name_change_generate '
    'portal_invoice_name_change_sent portal_invoice_name_change_replacement',
    authentication=_PORTAL_AUTH, capability='portal.invoice_identity.manage', scope=_PORTAL_SCOPE,
    request_key_binding=_PORTAL_KEY,
    domain_replay='Request-keyed identity/household/batch event plus immutable identity and status constraints',
)
_add(
    'portal_payment_selection portal_payment_document_preview portal_payment_document_finalize',
    authentication=_PORTAL_AUTH, capability='portal.payment.prepare', scope=_PORTAL_SCOPE,
    request_key_binding=_PORTAL_KEY,
    domain_replay='Selection/document request uniqueness, source workbook hash, revision, and finalization state',
)
_add(
    'portal_payment_document_approve', authentication=_PORTAL_AUTH,
    capability='portal.payment.approve', scope=_PORTAL_SCOPE,
    request_key_binding=_PORTAL_KEY,
    domain_replay='Request-keyed approval event plus immutable document/version and terminal approval state',
)
_add(
    'portal_payment_document_regenerate', authentication=_PORTAL_AUTH,
    capability='portal.documents.regenerate', scope=_PORTAL_SCOPE,
    request_key_binding=_PORTAL_KEY,
    domain_replay='Request-keyed new document version; prior document remains immutable',
)
_add(
    'portal_document_physical_signoff_upload portal_document_physical_signoff_retry',
    authentication=_PORTAL_AUTH, capability='portal.documents.sign', scope=_PORTAL_SCOPE,
    request_key_binding=_PORTAL_KEY,
    domain_replay='Request key, scan content hash, source workbook hash, signoff version, durable Drive operation',
)


# Write-like endpoints in the same URL module that are deliberately not
# Telegram Mini App routes. They remain governed by their own boundary and
# must be reviewed explicitly instead of silently disappearing from CI.
NON_MINIAPP_WRITE_ROUTES: dict[str, str] = {
    'loan_origination_signer_consent': 'Public opaque signer session; request-keyed signer consent service.',
    'loan_origination_signer_otp': 'Public opaque signer session; throttled OTP request service.',
    'loan_origination_signer_verify': 'Public opaque signer session; request-keyed OTP verification service.',
    'loan_origination_africastalking_delivery': 'Authenticated provider delivery webhook.',
    'tat_signature_webhook': 'Authenticated e-signature provider webhook.',
    'telegram_webhook': 'Telegram webhook secret and Telegram update/message identifiers.',
    'process_messages': 'Token-authenticated operator API, not a Mini App route.',
    'resend_unsynced': 'Token-authenticated operator API, not a Mini App route.',
    'sync_from_sheets': 'Token-authenticated disabled legacy API.',
}
