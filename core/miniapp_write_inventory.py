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
    'portal_hb_deposit_update',
    authentication='portal_auth_required; verified Telegram initData and active staff',
    capability='portal.hb_deposit.write',
    scope='One complete Portal group/branch/product grant tuple; current intake group',
    request_key_binding='Canonical Portal request identity plus farmer and normalized amount/reason payload',
    domain_replay='Locked farmer; unique pipeline request event; original-payload replay before revision/visit lock; durable publication reservation',
)

_add(
    'loan_origination_phone_identity_checks',
    authentication='origination_auth_required; verified Telegram identity and active account',
    capability='origination.identity.phone.verify plus scoped IT-only pilot restriction',
    scope='Full saved application; one complete Origination IT group/branch/product tuple',
    request_key_binding='origination_auth_required plus canonical Mini App request identity',
    domain_replay='Immutable application request receipt; shared subject lock, unique in-flight check and single-dispatch fencing',
)

_add(
    'ui_review_revision ui_review_decision ui_review_upload ui_review_release',
    authentication='Verified Telegram initData or CSRF-checked authenticated Django session',
    capability='Current active Django Superuser only; feature flag required; no workflow role inheritance',
    scope='Source-bound synthetic design revision only; never operational customer records',
    request_key_binding='ui_review_auth_required plus canonical source/evidence fingerprints or exact actor-bound UUID request key',
    domain_replay='Unique revision digest, evidence-content deduplication, or immutable decision/release request-key replay; conflicting meaning rejected',
)


_add(
    'tat_tracker_recovery_status complaint_recovery_status',
    authentication='Verified owning Mini App Telegram identity and current access grants',
    capability='tat.home.view or complaint.queue.view, within that app only',
    scope='Selected group plus the owning workflow current-access projection',
    request_key_binding='miniapp_write_response',
    domain_replay='Read-only status projection; POST carries the existing authenticated Mini App context',
)
_add(
    'tat_tracker_recovery_retry',
    authentication='Verified TAT Telegram identity and current complete grant tuples',
    capability='tat.publication.retry, Sheet effects only',
    scope='Selected group, exact existing case/remark, operational data mode and current revision',
    request_key_binding='miniapp_write_response',
    domain_replay='Locked existing dispatch/operation; pending/running/completed work is not reset',
)
_add(
    'loan_origination_signature_preview',
    authentication='Verified Telegram identity or exact opaque signer-session token',
    capability='Existing Origination staff signing or TEST start capability; public session is signing-only',
    scope='Currently accessible application revision/package or unexpired signer session',
    request_key_binding='Read-only deterministic name/font rendering; no workflow writes',
    domain_replay='Repeated previews return the same image hash without creating signatures or events',
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


_add(
    'tat_tracker_comments',
    authentication='Canonical signed Telegram identity through _tat_context',
    capability='tat.home.view, rechecked against current grants',
    scope='Exact in-scope case; deleted, unresolved and closed Pilot cases denied',
    request_key_binding='miniapp_write_response plus required canonical key',
    domain_replay='Unique case/request event, actor/text conflict check, event-keyed Sheet operation',
)

_ORIGINATION_AUTH = 'Canonical Telegram identity through portal_auth_required'
_ORIGINATION_SCOPE = 'Origination AccessGrant capability plus application branch/ownership scope'
_ORIGINATION_KEY = 'origination_auth_required -> canonical request identity'
_ORIGINATION_REPLAY = 'Request-keyed append-only event plus application revision/state constraints'

_add(
    'loan_origination_applications',
    authentication=_ORIGINATION_AUTH,
    capability='origination.create',
    scope='Authorized branch and active product availability',
    request_key_binding=_ORIGINATION_KEY,
    domain_replay='Application create request key and product/schema snapshot uniqueness',
)
_add(
    'loan_origination_prepare_download',
    authentication=_ORIGINATION_AUTH, capability='origination.view', scope=_ORIGINATION_SCOPE,
    request_key_binding=_ORIGINATION_KEY,
    domain_replay='Revision/document-bound copy request; expiring actor-bound download token; no review, signature or approval',
)
_add(
    'loan_origination_application_detail',
    methods=('PATCH',), authentication=_ORIGINATION_AUTH,
    capability='origination.create', scope=_ORIGINATION_SCOPE,
    request_key_binding=_ORIGINATION_KEY,
    domain_replay='Draft request key plus optimistic application revision and payload conflict check',
)
_add(
    'loan_origination_quote_preview loan_origination_submit loan_origination_confirm_signing '
    'loan_origination_recall loan_origination_restart loan_origination_document_selection loan_origination_document_fields',
    authentication=_ORIGINATION_AUTH,
    capability='origination.create', scope=_ORIGINATION_SCOPE,
    request_key_binding=_ORIGINATION_KEY, domain_replay=_ORIGINATION_REPLAY,
)
_add(
    'loan_origination_document_updates',
    authentication=_ORIGINATION_AUTH, capability='origination.create',
    scope=_ORIGINATION_SCOPE + '; assigned officer only',
    request_key_binding=_ORIGINATION_KEY,
    domain_replay='Locked application; deterministic revision/update-plan key; confirmed signatures freeze the bundle',
)
_add(
    'loan_origination_preview loan_origination_document_preview '
    'loan_origination_packet_preview loan_origination_review_packet_preview',
    authentication=_ORIGINATION_AUTH,
    capability='origination.view', scope=_ORIGINATION_SCOPE,
    request_key_binding=_ORIGINATION_KEY,
    domain_replay='Revision-bound deterministic render and request-keyed preview event',
)
_add(
    'loan_origination_review loan_origination_final_review '
    'loan_origination_correction_takeover loan_origination_reviewer_notice_seen',
    authentication=_ORIGINATION_AUTH,
    capability='origination.review', scope=_ORIGINATION_SCOPE,
    request_key_binding=_ORIGINATION_KEY, domain_replay=_ORIGINATION_REPLAY,
)
_add(
    'loan_origination_prepare_review_packet loan_origination_prepare_signing '
    'loan_origination_signer_sessions loan_origination_reset_signer_session '
    'loan_origination_production_stamp loan_origination_archive_signed '
    'loan_origination_signing_requirements loan_origination_test_signing_action '
    'loan_origination_test_signing_preview',
    authentication=_ORIGINATION_AUTH,
    capability='origination.signing.start', scope=_ORIGINATION_SCOPE,
    request_key_binding=_ORIGINATION_KEY,
    domain_replay='Request-key uniqueness plus immutable package/session/document hashes',
)
_add(
    'loan_origination_staff_signature',
    authentication=_ORIGINATION_AUTH,
    capability='origination.signing.staff', scope=_ORIGINATION_SCOPE,
    request_key_binding=_ORIGINATION_KEY,
    domain_replay='Signer-slot/request uniqueness plus exact packet hash binding',
)
_add(
    'loan_origination_evidence_upload loan_origination_evidence_remove',
    authentication=_ORIGINATION_AUTH,
    capability='origination.create or origination.signing.start',
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
    'complaint_cases_bootstrap complaint_cases_list complaint_cases_list_fragment complaint_cases_detail '
    'complaint_cases_global_overview complaint_cases_global_list complaint_cases_global_detail',
    authentication=_COMPLAINT_AUTH,
    capability='complaint.queue.view / complaint.case.source.view', scope=_COMPLAINT_SCOPE,
    request_key_binding='complaint miniapp_write_response',
    domain_replay='Read-only POST; no canonical workflow mutation',
)
_add(
    'complaint_cases_global_export',
    authentication=_COMPLAINT_AUTH, capability='complaint.case.export',
    scope='Organization-wide Complaint Cases allowlist after explicit all-case confirmation',
    request_key_binding='Canonical Mini App request identity',
    domain_replay='Idempotent sensitive export audit event keyed by actor and request ID',
)
_add(
    'complaint_cases_settings_personal',
    authentication=_COMPLAINT_AUTH, capability='complaint.queue.view',
    scope='Canonical user preference', request_key_binding='complaint miniapp_write_response',
    domain_replay='Unique user/workflow preference row',
)
_add(
    'complaint_cases_category_suggestion',
    authentication=_COMPLAINT_AUTH, capability='complaint.queue.view', scope=_COMPLAINT_SCOPE,
    request_key_binding='complaint miniapp_write_response',
    domain_replay='Advisory category inference only; no complaint creation or transition; governed inference service owns provider attempts',
)
_add(
    'complaint_cases_complete_details',
    authentication=_COMPLAINT_AUTH, capability='complaint.case.details.complete', scope=_COMPLAINT_SCOPE,
    request_key_binding='complaint miniapp_write_response plus required canonical key',
    domain_replay='Expected revision and request-keyed completion event; original incomplete intake remains auditable',
)
_add(
    'complaint_cases_finish_created',
    authentication=_COMPLAINT_AUTH, capability='complaint.case.create', scope=_COMPLAINT_SCOPE,
    request_key_binding='complaint miniapp_write_response plus required canonical key',
    domain_replay='Exact existing creation request plus content-hash evidence reuse and existing publication operations',
)
_add(
    'complaint_cases_voice_transcription complaint_cases_voice_transcription_cancel',
    authentication=_COMPLAINT_AUTH,
    capability='Action-specific complaint.case.create, complaint.case.comment, complaint.case.close or complaint.case.reopen',
    scope='Actor/group-owned transcription and its accessible case/action',
    request_key_binding='complaint miniapp_write_response plus canonical request binding',
    domain_replay='Existing voice-attempt request/ownership and resolution state; no complaint decision or automatic retry',
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
    'complaint_cases_comment',
    authentication=_COMPLAINT_AUTH, capability='complaint.case.comment', scope=_COMPLAINT_SCOPE,
    request_key_binding='complaint miniapp_write_response',
    domain_replay='Unique comment request, payload binding, and expected case revision',
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
    'portal_create_and_complete_jbl_lead',
    authentication=_PORTAL_AUTH, capability='portal.jbl_lead.create and portal.jbl_media.write for evidence',
    scope='Selected authorized Portal group, actor/request intake identity and canonical customer uniqueness',
    request_key_binding=_PORTAL_KEY,
    domain_replay='Actor/request external ID plus visit event replay and retained media hashes; only untouched failed intake may be discarded',
)
_add(
    'portal_farmer_case_correction',
    authentication=_PORTAL_AUTH, capability='portal.case.correct', scope=_PORTAL_SCOPE,
    request_key_binding=_PORTAL_KEY, domain_replay='Request-keyed case correction plus expected workflow revision and audited field allowlist',
)
_add(
    'portal_import_commit',
    authentication=_PORTAL_AUTH, capability='portal.imports.commit',
    scope='Authorized import kind, owning group and retained staged batch',
    request_key_binding=_PORTAL_KEY,
    domain_replay='Staged review revision, source-row identity, selected field choices and existing canonical commit state',
)
_add(
    'portal_farmup_version portal_farmup_mapping',
    authentication=_PORTAL_AUTH, capability='portal.farmup.stage',
    scope='Current Portal group grant and exact monthly FarmUp batch/version',
    request_key_binding=_PORTAL_KEY,
    domain_replay='Request/content digest, immutable source version and signed batch review revision',
)
_add(
    'portal_farmup_validate',
    authentication=_PORTAL_AUTH, capability='portal.farmup.commit',
    scope='Exact group-scoped FarmUp batch and signed review revision',
    request_key_binding=_PORTAL_KEY,
    domain_replay='Deterministic review validation; does not commit selected intake rows or publish Google data',
)
_add(
    'portal_farmup_repair',
    authentication=_PORTAL_AUTH, capability='portal.publication.retry',
    scope='Current Portal group and exact retained FarmUp batch/review revision',
    request_key_binding=_PORTAL_KEY,
    domain_replay='Request-keyed repair of existing batch publication/archive work; canonical committed rows are not imported again',
)
_add(
    'portal_curated_report portal_curated_report_export portal_curated_report_email',
    authentication=_PORTAL_AUTH,
    capability='portal.reports.view; email additionally requires current scoped IT disclosure authority',
    scope='Allowlisted Portal preset and current case/group/branch/product filters; approved email recipients',
    request_key_binding=_PORTAL_KEY,
    domain_replay='Read-only query/export with request-bound audit; email reserves durable request-keyed delivery, never a financial transition',
)
_add(
    'portal_report_settings portal_report_send_now',
    authentication=_PORTAL_AUTH, capability='report_delivery.require_manage: active Superuser or current complete Portal IT grant',
    scope='Portal-owned report configuration, approved recipients and complete current disclosure scope',
    request_key_binding=_PORTAL_KEY,
    domain_replay='Revision-bound configuration and request-keyed delivery reservation; status wakes existing deliveries rather than resending',
)
_add(
    'portal_publication_pump',
    authentication=_PORTAL_AUTH, capability='At least one current Portal capability; no new workflow-write authority',
    scope='Existing Portal-owned publication or invoice-cleanup operation only; caller supplies no case or document selection',
    request_key_binding=_PORTAL_KEY,
    domain_replay='Existing durable operation lease, destination FIFO, attempt fencing and terminal-state guards',
)
_add(
    'portal_requisition_batch_cancel',
    authentication=_PORTAL_AUTH, capability='portal.requisition.finalize', scope=_PORTAL_SCOPE,
    request_key_binding=_PORTAL_KEY,
    domain_replay='Locked exact order UUID/version and allocator claim; request replay; accepted signed or financially connected work cannot be cancelled',
)
_add(
    'portal_invoice_receipt_archive portal_invoice_receipt_batch_payment',
    authentication=_PORTAL_AUTH, capability='portal.payment.prepare',
    scope='Exact group-scoped invoice delivery and every linked case', request_key_binding=_PORTAL_KEY,
    domain_replay='Receipt revision and request-keyed archive/payment event; one durable linked payment batch, never invoice deletion',
)
_add(
    'portal_invoice_receipt_item_replacement portal_invoice_name_agreement',
    authentication=_PORTAL_AUTH, capability='portal.invoice_identity.manage',
    scope='Exact receipt group/item or sent-letter artifact and every current linked case', request_key_binding=_PORTAL_KEY,
    domain_replay='Locked receipt revision or exact signed-letter checksum/identity facts; superseded evidence and completed payments remain protected',
)
_add(
    'portal_tat_target_settings',
    authentication=_PORTAL_AUTH, capability='portal.tat.targets.manage',
    scope='Enabled Portal-owned workflow configuration; never TAT Tracker or Origination authority',
    request_key_binding=_PORTAL_KEY,
    domain_replay='Governed target validation and durable configuration/audit save; no case transition',
)

# These are inventory-only descriptions of existing TAT contracts. They do not
# add capabilities, change policy defaults, or grant Portal users TAT access.
_add(
    'tat_tracker_recognition tat_tracker_recognition_revision',
    authentication='Canonical Telegram identity through _tat_context',
    capability='tat.recognition.view; people view additionally requires tat.recognition.people.view',
    scope='Selected TAT group, current complete grants, period and view',
    request_key_binding='miniapp_write_response',
    domain_replay='Read projection plus uniquely bound live checkpoint/final snapshot; never workflow stage or scoring-fact rewrites',
)
_add(
    'tat_tracker_reports_summary tat_tracker_reports_cases tat_tracker_reports_export',
    authentication='Canonical Telegram identity through _tat_context',
    capability='tat.reports.view plus current people/insight capabilities where requested',
    scope='Selected group, authorized cases, exact allowlisted report filters and data mode',
    request_key_binding='miniapp_write_response',
    domain_replay='Read-only report query/export and audit; expiring download retains actor/current-access checks',
)
_add(
    'tat_tracker_task_read',
    authentication='Canonical Telegram identity through _tat_context', capability='tat.home.view',
    scope='Current group, accessible case and actor-owned private task',
    request_key_binding='miniapp_write_response plus canonical request binding',
    domain_replay='Idempotent task-read timestamp; no stage or assignment mutation',
)
_add(
    'tat_tracker_target_sheet_sync',
    authentication='Canonical Telegram identity through _tat_context',
    capability='tat_recovery.can_retry_targets: complete group-wide TAT IT scope',
    scope='Selected TAT group and existing canonical target mirror',
    request_key_binding='miniapp_write_response plus canonical request binding',
    domain_replay='Retry existing governed mirror with durable operation/state guards; database targets remain authoritative',
)
_add(
    'tat_tracker_process_update_dispatches',
    authentication='Canonical Telegram identity through _tat_context', capability='tat.home.view',
    scope='Up to three exact existing dispatches in the selected group; every case reauthorized',
    request_key_binding='miniapp_write_response plus canonical request binding',
    domain_replay='Database-leased existing side-effect dispatches; terminal work is not recreated or replayed',
)

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
    'portal_farmup_stage portal_farmup_commit portal_farmup_archive portal_farmup_archive_attempt',
    authentication=_PORTAL_AUTH,
    capability='portal.farmup.stage or portal.farmup.commit',
    scope='FarmUp kind plus explicit Jawabu AccessGrant group scope',
    request_key_binding=_PORTAL_KEY,
    domain_replay='Upload hash or signed batch revision plus request-key/payload-digest replay ledger',
)
_add(
    'portal_report_preview portal_reports portal_report_detail portal_report_archive',
    authentication=_PORTAL_AUTH, capability='portal.reports.manage',
    scope='IT-only report owner and catalogue-constrained definition', request_key_binding=_PORTAL_KEY,
    domain_replay='Request-keyed definition/audit event plus report revision/archive state',
)
_add(
    'portal_invoice_cleanup', authentication=_PORTAL_AUTH,
    capability='portal.invoice.write', scope='Complete authorized grant matching retained cleanup scope',
    request_key_binding=_PORTAL_KEY,
    domain_replay='Durable file-specific IntegrationOperation lease and success replay; bounded retry',
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
    'portal_requisition_preview portal_requisition_finalize',
    authentication=_PORTAL_AUTH, capability='portal.requisition.finalize', scope=_PORTAL_SCOPE,
    request_key_binding=_PORTAL_KEY,
    domain_replay='Signed preview hash, exact payload digest, case revisions, and official sequence lock',
)
_add(
    'portal_requisition_numbering',
    authentication=_PORTAL_AUTH, capability='portal.requisition.sequence.manage', scope=_PORTAL_SCOPE,
    request_key_binding=_PORTAL_KEY,
    domain_replay='Group sequence revision, immutable request-keyed adjustment event, and finalized-number floor',
)
_add(
    'portal_requisition_workbook_preview portal_requisition_generate portal_assign_order portal_requisition_batch_retry_sync',
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
    'portal_invoice_name_change_correct_sent portal_invoice_name_change_batches portal_invoice_name_change_close '
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
    'portal_payment_batches portal_payment_batch_cases portal_payment_batch_case_mode portal_payment_batch_case_remove '
    'portal_payment_batch_submit portal_payment_batch_case_review portal_payment_batch_generate '
    'portal_payment_batch_cancel',
    authentication=_PORTAL_AUTH,
    capability='Governed payment preparation or Head of Rural review capability',
    scope='One group-scoped payment batch and its fully scoped active cases',
    request_key_binding=_PORTAL_KEY,
    domain_replay='Request-keyed payment event plus batch revision, case digest, state, and active-membership constraints',
)
_add(
    'portal_payment_sequence',
    methods=('PATCH',), authentication=_PORTAL_AUTH,
    capability='Payment preparation or IT-only payment sequence management',
    scope='One scoped payment batch or Jawabu group payment sequence',
    request_key_binding=_PORTAL_KEY,
    domain_replay='Request-keyed payment event plus locked batch/sequence state and allocated-number floor',
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
# Telegram Mini App business-write routes. They remain governed by their own boundary and
# must be reviewed explicitly instead of silently disappearing from CI.
NON_MINIAPP_WRITE_ROUTES: dict[str, str] = {
    'miniapp_available': 'Read-only launcher discovery, not a workflow submission: canonical Telegram authentication, active account, IP throttle and fresh per-app grants; no business mutation or retry key required.',
    'loan_origination_signer_signature_preview': 'Read-only deterministic image render; opaque session credential and public signing throttle; no signature or workflow write.',
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
