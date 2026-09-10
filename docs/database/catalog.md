# Database Catalogue

Generated from the current Django model graph. PostgreSQL remains authoritative for live row and storage estimates.

| Domain | Table | Django model | Classification | Lifecycle | Purpose |
|---|---|---|---|---|---|
| access | `core_accesscontrolchangerequest` | `core.AccessControlChangeRequest` | authoritative_record | active | Maker-checker request for permanent Mini App access changes. |
| access | `core_accesscontrolcheckerassignment` | `core.AccessControlCheckerAssignment` | business_assignment | active | Auditable appointment of an independent Mini App access checker. Django superusers are root technical approvers and therefore do not need an assignment. Non-superuser checkers are appointed only through the access control service so the designation, its reason, and any later revocation remain visible in the compliance ledger. |
| access | `core_accesscontrolnotification` | `core.AccessControlNotification` | authoritative_record | active | Delivery ledger; notification failure never undoes an applied control. |
| access | `core_accesscontrolpolicysnapshot` | `core.AccessControlPolicySnapshot` | authoritative_record | active | Immutable recoverable state created whenever an approved request applies. |
| access | `core_accesscontrolpolicystate` | `core.AccessControlPolicyState` | configuration_state | active | Single locked counter used to prevent approval of a stale policy diff. |
| access | `core_accessgrant` | `core.AccessGrant` | authoritative_record | active | Workflow-specific scope supplementing Django Groups/Permissions. |
| catalog | `core_branchservicearea` | `core.BranchServiceArea` | authoritative_record | active | Current governed coverage of one branch over a county or sub-county. |
| tat | `core_businesscalendarholiday` | `core.BusinessCalendarHoliday` | authoritative_record | active | Admin-managed public holiday excluded from the official JBL SLA clock. |
| access | `core_capabilityusagedaily` | `core.CapabilityUsageDaily` | authoritative_record | active | Small daily aggregate used for least-privilege drift reports. |
| complaints | `core_caseupdate` | `core.CaseUpdate` | authoritative_record | active | Audit trail for chat-driven case status/resolution updates. |
| complaints | `core_complaintcasecontrol` | `core.ComplaintCaseControl` | authoritative_record | active | Operational control plane layered over immutable complaint source data. |
| complaints | `core_complaintcaseevent` | `core.ComplaintCaseEvent` | immutable_event | active | Append-only evidence of every governed complaint-case change. |
| complaints | `core_complaintcaseevidence` | `core.ComplaintCaseEvidence` | authoritative_record | active | Drive-backed, append-only evidence uploaded for a complaint case. |
| complaints | `core_complaintcaseimportbatch` | `core.ComplaintCaseImportBatch` | processing_record | active | Auditable source record for one Superuser-initiated complaint import. |
| complaints | `core_complaintcaseimportitem` | `core.ComplaintCaseImportItem` | processing_record | active | Immutable source snapshot plus resumable outcome for one import row. |
| complaints | `core_complaintcasesequence` | `core.ComplaintCaseSequence` | authoritative_record | active | Durable sequence scope for complaint identifiers and staff-facing references. |
| complaints | `core_complaintcategory` | `core.ComplaintCategory` | authoritative_record | active | Governed, reusable complaint category and its default service target. |
| complaints | `core_complaintcategoryalias` | `core.ComplaintCategoryAlias` | business_link | active | Legacy label resolved to one canonical complaint category. |
| complaints | `core_complaintcategoryavailability` | `core.ComplaintCategoryAvailability` | business_link | active | Optional category restriction to a configured Telegram workflow group. |
| audit | `core_complianceauditchainstate` | `core.ComplianceAuditChainState` | audit_evidence | active | Single locked cursor used to serialize the compliance-evidence chain. |
| audit | `core_complianceauditcheckpoint` | `core.ComplianceAuditCheckpoint` | immutable_snapshot | active | Supervised daily checkpoint of the compliance hash-chain head. |
| audit | `core_complianceauditevent` | `core.ComplianceAuditEvent` | immutable_event | active | Immutable cross-workflow compliance evidence in the verified hash chain. |
| platform | `core_deleteduseridentity` | `core.DeletedUserIdentity` | authoritative_record | active | Minimal identity and relationship manifest retained after hard deletion. |
| platform | `core_documentphysicalsignoff` | `core.DocumentPhysicalSignoff` | authoritative_record | active | Immutable physical-signature scan and the exact workbook it confirms. The system records an authorised staff attestation after a paper document has been signed and stamped. It does not manufacture or verify an electronic signature. |
| platform | `core_documentphysicalsignoffevent` | `core.DocumentPhysicalSignoffEvent` | immutable_event | active | Append-only audit trail for physical document sign-off attempts. |
| integration | `core_documentsignoffpolicy` | `core.DocumentSignoffPolicy` | configuration_state | active | Maker-checker controlled Portal roles allowed to attest physical sign-off. |
| platform | `core_durablejobrunnerheartbeat` | `core.DurableJobRunnerHeartbeat` | authoritative_record | temporary | Privacy-safe liveness evidence for database-backed scheduled runners. |
| access | `core_emergencyaccessgrant` | `core.EmergencyAccessGrant` | authoritative_record | active | Short-lived, separately audited access for an operational emergency. |
| jawabu | `core_fcaimportrecord` | `core.FcaImportRecord` | processing_record | active | Auditable staging and review row for one FCA workbook record. |
| platform | `core_groupsheetconfiguration` | `core.GroupSheetConfiguration` | configuration | active | Admin-managed routing and workflow configuration for a Telegram group. Environment settings remain supported as bootstrap/fallback config, but rows in this model are the editable UI source for group-specific sheets, schemas, workflows, and parser rules. |
| integration | `core_integrationcircuitstate` | `core.IntegrationCircuitState` | configuration_state | active | One persisted bounded circuit per outbound integration. |
| integration | `core_integrationoperation` | `core.IntegrationOperation` | authoritative_record | active | Durable, redacted record of a manually retriable external operation. This is an operations register, not a hidden task queue. No background worker is enabled: the owning workflow may retry a dead-lettered operation when its dependency is healthy. Raw payloads never belong here. |
| jawabu | `core_invoiceidentityreview` | `core.InvoiceIdentityReview` | authoritative_record | active | Append-oriented decision about invoice identity versus the JBL applicant. |
| jawabu | `core_invoicenamechangebatch` | `core.InvoiceNameChangeBatch` | processing_record | active | One manual/generated letter covering one or more invoice corrections. |
| jawabu | `core_invoicenamechangeitem` | `core.InvoiceNameChangeItem` | processing_record | active | A case-level correction preserving original and replacement invoices. |
| jawabu | `core_invoicenamechangeletterartifact` | `core.InvoiceNameChangeLetterArtifact` | authoritative_record | active | Immutable, versioned DOCX rendered from one name-change batch snapshot. |
| jawabu | `core_invoicenamechangelettertemplate` | `core.InvoiceNameChangeLetterTemplate` | configuration | active | Admin-governed DOCX template for invoice-name-change letters. |
| jawabu | `core_invoiceuploadbatch` | `core.InvoiceUploadBatch` | processing_record | active | Drive-backed invoice PDF upload batch kept before reconciliation. |
| jawabu | `core_jawabuapprovalcondition` | `core.JawabuApprovalCondition` | authoritative_record | active | A condition that blocks a conditional approval until explicitly cleared. |
| jawabu | `core_jawabuapprovaldelegation` | `core.JawabuApprovalDelegation` | authoritative_record | active | Time-boxed authority to approve one Portal gate for another staff user. |
| jawabu | `core_jawabuapprovaldelegationevent` | `core.JawabuApprovalDelegationEvent` | immutable_event | active | Append-only delegation lifecycle evidence. |
| jawabu | `core_jawabuapprovalrecord` | `core.JawabuApprovalRecord` | authoritative_record | active | Append-only effective/expired/inactivated approval evidence for one case. |
| jawabu | `core_jawabucasecomment` | `core.JawabuCaseComment` | authoritative_record | active | Immutable human-authored Portal remark projected to Master Data. |
| jawabu | `core_jawabucustomer` | `core.JawabuCustomer` | authoritative_record | active | Canonical Jawabu identity shared by one or more unit applications. |
| jawabu | `core_jawabucustomerfieldprovenance` | `core.JawabuCustomerFieldProvenance` | authoritative_record | active | Append-only source history for customer fields that cross system boundaries. |
| jawabu | `core_jawabucustomerphonehistory` | `core.JawabuCustomerPhoneHistory` | immutable_event | active | Observed customer phone numbers without discarding a previous SIM. |
| jawabu | `core_jawabudataqualityissue` | `core.JawabuDataQualityIssue` | authoritative_record | active | Active/resolved canonical-data warning for a Jawabu application. |
| jawabu | `core_jawabudataqualityresolution` | `core.JawabuDataQualityResolution` | authoritative_record | active | Append-only staff decision for a Jawabu data-quality exception. |
| jawabu | `core_jawabufarmermaster` | `core.JawabuFarmerMaster` | authoritative_record | active | Clean internal master data for Jawabu farmers used by visit forms. |
| jawabu | `core_jawabufarmeruploadbatch` | `core.JawabuFarmerUploadBatch` | processing_record | active | Staged FarmUp/system-export upload awaiting staff review and commit. The original source is retained as a bounded binary payload so an accepted import can be archived to Drive after a free-Render request returns. The parsed rows remain the review surface; they are not a replacement for the submitted source document. |
| jawabu | `core_jawabuhouseholdrelationship` | `core.JawabuHouseholdRelationship` | authoritative_record | active | Verified relationship used to explain an invoice issued to another person. |
| jawabu | `core_jawabumediaaccessevent` | `core.JawabuMediaAccessEvent` | immutable_event | active | Audit every Portal-mediated retrieval of sensitive JBL visit evidence. |
| jawabu | `core_jawabupipelineevent` | `core.JawabuPipelineEvent` | immutable_event | active | Append-only audit event for Jawabu application state changes. |
| jawabu | `core_jawaburelatedperson` | `core.JawabuRelatedPerson` | authoritative_record | active | A spouse/household member kept distinct from the applicant identity. |
| jawabu | `core_jawabuvisitrecord` | `core.JawabuVisitRecord` | authoritative_record | active | Audit/import record for Jawabu HomeBiogas WhatsApp visit exports. |
| integration | `core_livesheetrecordchange` | `core.LiveSheetRecordChange` | authoritative_record | active | Audit trail for Django admin edits and deletes applied to live sheet rows. |
| origination | `core_loanoriginationapplication` | `core.LoanOriginationApplication` | authoritative_record | active | Canonical, revision-controlled application captured by a field officer. |
| catalog | `core_locationconfigurationevent` | `core.LocationConfigurationEvent` | immutable_event | active | Append-only evidence for global location and coverage changes. |
| catalog | `core_locationmappingissue` | `core.LocationMappingIssue` | authoritative_record | active | Persists location mapping issues for the owning workflow. |
| catalog | `core_locationpolicystate` | `core.LocationPolicyState` | configuration_state | active | Persists Location enforcement policy for the owning workflow. |
| order_approval | `core_mediaattachment` | `core.MediaAttachment` | authoritative_record | active | Audit record for media uploaded from Telegram to external storage. |
| platform | `core_miniappdiagnosticdailyaggregate` | `core.MiniAppDiagnosticDailyAggregate` | derived_metric | active | Anonymous daily Mini App diagnostic trend totals. |
| platform | `core_miniappdiagnosticevent` | `core.MiniAppDiagnosticEvent` | operational_telemetry | temporary | Privacy-safe events belonging to a Mini App diagnostic session. |
| platform | `core_miniappdiagnosticsession` | `core.MiniAppDiagnosticSession` | operational_telemetry | temporary | Privacy-safe Mini App lifecycle session telemetry. |
| platform | `core_miniappdraft` | `core.MiniAppDraft` | authoritative_record | temporary | Short-lived, server-owned recovery state for interrupted Mini App work. Drafts intentionally hold fields only. Attachments remain on the device until the staff member explicitly submits the workflow action, so an interrupted upload never becomes an untracked copy of a customer document. |
| platform | `core_miniapplegacywritedailyaggregate` | `core.MiniAppLegacyWriteDailyAggregate` | derived_metric | compatibility | Anonymous readiness totals for outdated Mini App writes missing retry keys. |
| catalog | `core_operationallocation` | `core.OperationalLocation` | authoritative_record | active | Stable branch, county, or sub-county identity shared by all workflows. |
| catalog | `core_operationallocationalias` | `core.OperationalLocationAlias` | business_link | active | Approved legacy or alternate spelling for a canonical location. |
| order_approval | `core_orderapprovalupdate` | `core.OrderApprovalUpdate` | authoritative_record | archived | Audit trail for Telegram-driven order approval BRO updates. |
| origination | `core_originationapplicationdocument` | `core.OriginationApplicationDocument` | authoritative_record | active | Application-scoped snapshot and progress for one generated packet document. |
| origination | `core_originationapplicationevent` | `core.OriginationApplicationEvent` | immutable_event | active | Append-only operational history for an origination application. |
| origination | `core_originationcommercialexception` | `core.OriginationCommercialException` | authoritative_record | active | Immutable Superuser approval for exact policy mismatches on one revision. |
| origination | `core_originationconsentpolicyversion` | `core.OriginationConsentPolicyVersion` | authoritative_record | active | Immutable approved wording bound to a conditional signing packet. |
| origination | `core_originationcorrectionitem` | `core.OriginationCorrectionItem` | processing_record | active | Immutable field or requirement target within a correction request. |
| origination | `core_originationcorrectionrequest` | `core.OriginationCorrectionRequest` | authoritative_record | active | Append-preserving reviewer instructions for one submitted revision. |
| origination | `core_originationdatafield` | `core.OriginationDataField` | authoritative_record | active | Global semantic field used by product forms and legal PDF mappings. |
| origination | `core_originationdatafieldevent` | `core.OriginationDataFieldEvent` | immutable_event | active | Append-only, value-free audit trail for catalogue governance. |
| origination | `core_originationdocumentproducteligibility` | `core.OriginationDocumentProductEligibility` | business_link | active | Current product allowlist for one immutable Origination catalogue document version. |
| origination | `core_originationdocumenttemplate` | `core.OriginationDocumentTemplate` | configuration | active | Immutable Drive-backed PDF/config pair approved for origination rendering. |
| origination | `core_originationdocumenttemplateevent` | `core.OriginationDocumentTemplateEvent` | immutable_event | active | Append-only audit trail for legal template lifecycle changes. |
| origination | `core_originationfieldreviewissue` | `core.OriginationFieldReviewIssue` | authoritative_record | active | Tracked exit path for a legacy schema field without a safe catalogue binding. |
| origination | `core_originationotpchallenge` | `core.OriginationOtpChallenge` | processing_record | temporary | Hashed, bounded OTP challenge; provider delivery never proves signing. |
| origination | `core_originationproductdefinition` | `core.OriginationProductDefinition` | configuration | active | Versioned, inactive-by-default contract for one loan-origination form. |
| origination | `core_originationproductdefinitionevent` | `core.OriginationProductDefinitionEvent` | immutable_event | active | Append-only lifecycle history for a versioned origination product. |
| origination | `core_originationproductdocumentassignment` | `core.OriginationProductDocumentAssignment` | business_assignment | compatibility | Version-policy assignment between a legacy product definition and document family. |
| origination | `core_originationreportingvalue` | `core.OriginationReportingValue` | authoritative_record | active | Rebuildable typed projection of explicitly reportable application values. |
| origination | `core_originationrequirementevidence` | `core.OriginationRequirementEvidence` | authoritative_record | active | Audited Drive-backed evidence for one snapshotted product requirement. |
| origination | `core_originationreviewernotice` | `core.OriginationReviewerNotice` | authoritative_record | active | Persistent in-app attention item for an Origination checker. |
| origination | `core_originationsignersession` | `core.OriginationSignerSession` | authoritative_record | temporary | Revocable bearer session for one signer of one immutable packet. |
| origination | `core_originationsigningaction` | `core.OriginationSigningAction` | authoritative_record | active | Append-only evidence for one simulated or provider-verified slot action. |
| origination | `core_originationsigningactioninvalidation` | `core.OriginationSigningActionInvalidation` | authoritative_record | active | Append-only checker evidence invalidating one otherwise immutable action. |
| origination | `core_originationsigningpackage` | `core.OriginationSigningPackage` | authoritative_record | active | Stable cross-system link from one frozen revision to e-signatures. |
| origination | `core_originationsigningrequestevent` | `core.OriginationSigningRequestEvent` | immutable_event | active | Minimal append-only database throttle evidence for public signing writes. |
| origination | `core_originationstampasset` | `core.OriginationStampAsset` | authoritative_record | active | Versioned, controlled PNG used only in calibrated stamp slots. |
| origination | `core_originationtemplateconfigurationrevision` | `core.OriginationTemplateConfigurationRevision` | authoritative_record | active | Append-only saved calibration revision for one immutable source PDF. |
| jawabu | `core_parsedinvoice` | `core.ParsedInvoice` | authoritative_record | active | One parsed invoice page/record from a Drive-backed invoice upload batch. |
| jawabu | `core_parsedinvoiceevent` | `core.ParsedInvoiceEvent` | immutable_event | active | Append-only operational event for manual invoice reconciliation. |
| complaints | `core_parsedmessage` | `core.ParsedMessage` | authoritative_record | active | Structured data extracted from raw messages. Maps directly to Google Sheets schema. |
| jawabu | `core_paymentdocument` | `core.PaymentDocument` | authoritative_record | active | Drive-backed payment workbook, review snapshot, or final artifact. A workbook generated for operations is deliberately not a final payment. It remains a review snapshot until Head of Rural approves it and supplies the batch Call Up Comment used in the payment template's COL column. |
| jawabu | `core_paymentdocumenttemplate` | `core.PaymentDocumentTemplate` | configuration | active | Admin-uploaded Excel template used for HB payment document generation. |
| platform | `core_portalcaseworkspace` | `core.PortalCaseWorkspace` | authoritative_record | active | Private pin/recent metadata retained separately from the customer case. |
| platform | `core_portalmaintenancestate` | `core.PortalMaintenanceState` | configuration_state | active | Singleton operational mode for safe, staff-visible Portal maintenance. |
| platform | `core_portalreportchart` | `core.PortalReportChart` | authoritative_record | active | A constrained chart attached to a Portal report definition. |
| platform | `core_portalreportdefinition` | `core.PortalReportDefinition` | configuration | active | An IT-owned, validated definition for a read-only Portal report. The JSON configuration contains only keys from the server-owned Portal reporting catalogue. It intentionally never stores arbitrary ORM paths, SQL, source data, Drive links, or customer snapshots. |
| platform | `core_portalsavedview` | `core.PortalSavedView` | authoritative_record | active | A private, validated Portal workspace view; never a workflow assignment. |
| platform | `core_portalvoicetranscriptionattempt` | `core.PortalVoiceTranscriptionAttempt` | authoritative_record | active | Append-oriented audit and retry state for bounded Portal dictation. |
| complaints | `core_processedmessage` | `core.ProcessedMessage` | authoritative_record | active | Tracks which messages have been processed to prevent duplicates. message_hash is the deduplication key. |
| catalog | `core_product` | `core.Product` | authoritative_record | active | Stable global identity for a financial product used by every workflow. |
| catalog | `core_productalias` | `core.ProductAlias` | business_link | active | Approved external/import spelling for one canonical product. |
| catalog | `core_productavailability` | `core.ProductAvailability` | business_link | active | Persists product availabilitys for the owning workflow. |
| catalog | `core_productcustomattribute` | `core.ProductCustomAttribute` | authoritative_record | active | Persists product custom attributes for the owning workflow. |
| catalog | `core_productfee` | `core.ProductFee` | authoritative_record | active | Persists product fees for the owning workflow. |
| catalog | `core_productionreleaseaudit` | `core.ProductionReleaseAudit` | audit_evidence | active | Durable, secret-free evidence and attempt history for one release. |
| catalog | `core_productmappingissue` | `core.ProductMappingIssue` | authoritative_record | active | Persists product mapping issues for the owning workflow. |
| catalog | `core_productrequirement` | `core.ProductRequirement` | authoritative_record | active | Persists product requirements for the owning workflow. |
| catalog | `core_producttatconfiguration` | `core.ProductTatConfiguration` | configuration | active | Versioned TAT and Sheet adapter for one product version. |
| catalog | `core_productversion` | `core.ProductVersion` | authoritative_record | active | Immutable, effective-dated commercial terms for a global product. |
| catalog | `core_productversionevent` | `core.ProductVersionEvent` | immutable_event | active | Append-only product-terms publication and lifecycle evidence. |
| platform | `core_publicendpointthrottlebucket` | `core.PublicEndpointThrottleBucket` | authoritative_record | active | Fixed-window abuse counter keyed only by a one-way privacy-safe digest. |
| complaints | `core_rawmessage` | `core.RawMessage` | authoritative_record | active | Stores original message data for traceability. Never modified after creation - audit trail guarantee. |
| jawabu | `core_requisitionbatch` | `core.RequisitionBatch` | processing_record | active | Generated requisition/order batch output kept for portal reference. |
| jawabu | `core_requisitiontemplate` | `core.RequisitionTemplate` | configuration | active | Admin-uploaded Excel templates used for Requisition/Order generation. |
| integration | `core_sheetregistercontract` | `core.SheetRegisterContract` | authoritative_record | active | Admin-owned publication contract for one Sheets operational register. Contracts make the field-level owner explicit even though the current platform deliberately supports only Django-to-Sheets publication. They are never an authorization or inbound-import mechanism. |
| integration | `core_sheetsyncauditsnapshot` | `core.SheetSyncAuditSnapshot` | audit_evidence | active | Append-only outcome of one read-only Sheet register audit. |
| integration | `core_sheetsyncdiscrepancy` | `core.SheetSyncDiscrepancy` | authoritative_record | active | One privacy-preserving difference found by a register audit. |
| spin | `core_spinbatchreviewitem` | `core.SpinBatchReviewItem` | processing_record | active | An uncertain WhatsApp batch message retained for staff classification. |
| spin | `core_spincreditrequest` | `core.SpinCreditRequest` | authoritative_record | active | Parsed SPIN / CRB request imported from WhatsApp exports or Mini App forms. |
| spin | `core_spinrequestsequence` | `core.SpinRequestSequence` | authoritative_record | active | Durable per-group/year sequence for staff-facing SPIN references. |
| access | `core_stafflifecyclechangeplan` | `core.StaffLifecycleChangePlan` | authoritative_record | active | One atomic direct or independently reviewed staff authority change. |
| access | `core_stafftelegramgroupinvitation` | `core.StaffTelegramGroupInvitation` | authoritative_record | active | One governed, expiring Telegram-group invitation for staff onboarding. |
| access | `core_stafftelegramonboarding` | `core.StaffTelegramOnboarding` | authoritative_record | active | Durable Telegram handoff created by an applied staff onboarding plan. |
| tat | `core_tatactiontask` | `core.TatActionTask` | processing_record | active | Durable, revision-bound inbox task for the next TAT stage. |
| tat | `core_tatactiontasklocator` | `core.TatActionTaskLocator` | authoritative_record | active | Hash-only record for an issued task deep link; raw tokens are never stored. |
| tat | `core_tatactiontaskrecipient` | `core.TatActionTaskRecipient` | authoritative_record | active | Per-user inbox and private-delivery state for one TAT task. |
| tat | `core_tatcasesequence` | `core.TatCaseSequence` | authoritative_record | active | Durable TAT case counter; purging pilot rows must never reuse a case ID. |
| tat | `core_tatconfigurationevent` | `core.TatConfigurationEvent` | immutable_event | active | Append-only evidence for guided TAT configuration changes. |
| tat | `core_tatescalationrule` | `core.TatEscalationRule` | authoritative_record | active | Approved, branch-aware escalation routing for the TAT tracker. |
| tat | `core_tatgroupexceptionstatus` | `core.TatGroupExceptionStatus` | authoritative_record | active | One cumulative, privacy-safe group notification for unreachable tasks. |
| tat | `core_tatnotificationprocessorrun` | `core.TatNotificationProcessorRun` | authoritative_record | active | Privacy-safe, append-oriented health evidence for the TAT alert runner. |
| tat | `core_tatpresentationsettings` | `core.TatPresentationSettings` | configuration_state | active | Global, audited presentation policy for the TAT Mini App. |
| tat | `core_tatprivatealertconnection` | `core.TatPrivateAlertConnection` | authoritative_record | active | TAT-only knowledge of whether Telegram can privately reach a user. |
| tat | `core_tatprivatealertconnectionevent` | `core.TatPrivateAlertConnectionEvent` | immutable_event | active | Append-only connection and delivery evidence for private TAT alerts. |
| tat | `core_tatrepairjob` | `core.TatRepairJob` | processing_record | active | Persistent progress for an asynchronous TAT Sheet repair. |
| tat | `core_tatresponsibilityassignment` | `core.TatResponsibilityAssignment` | business_assignment | active | Operational TAT owner for one scoped role, without granting access. |
| tat | `core_tatresponsibilitybackup` | `core.TatResponsibilityBackup` | authoritative_record | active | Ordered, SLA-triggered backup for a responsibility assignment. |
| tat | `core_tatresponsibilitychangeplan` | `core.TatResponsibilityChangePlan` | authoritative_record | active | Durable, revision-checked plan for an operational roster change. |
| tat | `core_tatresponsibilityevent` | `core.TatResponsibilityEvent` | immutable_event | active | Append-only evidence for changes to TAT operational ownership. |
| tat | `core_tattaskrerouteevent` | `core.TatTaskRerouteEvent` | immutable_event | active | Append-only evidence for one explicit reroute of a pending TAT task. |
| tat | `core_tattrackerapprovalcertificate` | `core.TatTrackerApprovalCertificate` | authoritative_record | active | External e-signature evidence for a completed TAT approval stage. |
| tat | `core_tattrackercase` | `core.TatTrackerCase` | authoritative_record | active | Authoritative TAT case and its current workflow stage. |
| tat | `core_tattrackerevent` | `core.TatTrackerEvent` | immutable_event | active | Append-only audit event for TAT tracker case creation and stage updates. |
| tat | `core_tatupdatesideeffectdispatch` | `core.TatUpdateSideEffectDispatch` | authoritative_record | active | Durable, privacy-safe work created after an authoritative TAT update. |
| platform | `core_telegramstaffactivation` | `core.TelegramStaffActivation` | authoritative_record | active | Hashed, short-lived proof for the first Telegram staff binding. |
| platform | `core_userharddeletionbatch` | `core.UserHardDeletionBatch` | processing_record | active | Immutable evidence for one Superuser-authorised physical user deletion. |
| platform | `core_userminiapppreference` | `core.UserMiniAppPreference` | authoritative_record | active | Validated, user-owned preferences kept separate from Telegram identity. |
| access | `core_userprofile` | `core.UserProfile` | authoritative_record | active | Telegram identity attached to Django's canonical staff account. |
| platform | `core_workflowconfigurationchangerequest` | `core.WorkflowConfigurationChangeRequest` | authoritative_record | active | Maker-checker proposal for high-impact workflow configuration. |
| platform | `core_workflowdatamodeevent` | `core.WorkflowDataModeEvent` | immutable_event | active | Append-only, non-PII evidence for mode, cycle, and purge actions. |
| platform | `core_workflowdatamodestate` | `core.WorkflowDataModeState` | configuration_state | active | Singleton switchboard for SPIN/TAT creation modes and active pilot cycles. |
| platform | `core_workflowpilotformulareadiness` | `core.WorkflowPilotFormulaReadiness` | authoritative_record | active | Superuser acknowledgement that deleting rows is safe for one Sheet layout. |
| platform | `core_workflowpilotpurgerun` | `core.WorkflowPilotPurgeRun` | authoritative_record | active | Durable manifest and progress for a resumable, verified pilot purge. |
| access | `core_workflowrolecapability` | `core.WorkflowRoleCapability` | authoritative_record | active | An administrator-managed capability assignment for a controlled role. Roles and capability keys are deliberately code-owned. This table only decides which of those reviewed capabilities a role receives; it cannot create a new unguarded permission by typo or by an Admin edit. |
| access | `core_workflowrolecapabilityauditevent` | `core.WorkflowRoleCapabilityAuditEvent` | immutable_event | active | Append-only record of a policy-matrix change made in Django Admin. |
| platform | `core_workflowslaescalation` | `core.WorkflowSlaEscalation` | authoritative_record | active | Idempotent overdue-stage record for supervised operational follow-up. |
| tat | `core_workflowtatdailymetric` | `core.WorkflowTatDailyMetric` | derived_metric | active | Idempotent daily operational TAT trend snapshot. This is a reporting projection only. It never replaces workflow events or changes a case's current state. |
| tat | `core_workflowtatmetricrebuildrequest` | `core.WorkflowTatMetricRebuildRequest` | authoritative_record | active | Durable, mergeable request to rebuild corrected TAT report dates. |
| platform | `core_workflowtimelineannotation` | `core.WorkflowTimelineAnnotation` | authoritative_record | active | Append-only correction/redaction evidence for a projected timeline entry. Original workflow events remain immutable. This record carries the relationship to the original entry and, when authorised, masks sensitive display content without destroying the event shell required for audit. |

## Relationship and usage details

### `core_accesscontrolchangerequest`

- Application identity: `core.AccessControlChangeRequest` in **Access**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.AccessControlChangeRequest`
- Children: `core.AccessControlChangeRequest`, `core.AccessControlNotification`, `core.AccessControlPolicySnapshot`
- Cross-domain parents: None
- Direct ORM writers: `core/services/access_control.py`, `core/services/user_hard_delete.py`
- Used by: `core/services/access_control.py`, `core/services/access_control_reporting.py`, `core/services/business_admin.py`, `core/services/user_hard_delete.py`

### `core_accesscontrolcheckerassignment`

- Application identity: `core.AccessControlCheckerAssignment` in **Access**
- Source of truth: **Yes**
- Retention: Retain while referenced; retire or deactivate instead of deleting governed history.
- Parents: `auth.User`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/access_control.py`, `core/services/user_hard_delete.py`
- Used by: `core/services/access_control.py`, `core/services/user_hard_delete.py`

### `core_accesscontrolnotification`

- Application identity: `core.AccessControlNotification` in **Access**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.AccessControlChangeRequest`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/access_control.py`, `core/services/user_hard_delete.py`
- Used by: `core/services/access_control.py`, `core/services/user_hard_delete.py`

### `core_accesscontrolpolicysnapshot`

- Application identity: `core.AccessControlPolicySnapshot` in **Access**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.AccessControlChangeRequest`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/access_control.py`, `core/services/staff_lifecycle.py`
- Used by: `core/services/access_control.py`, `core/services/access_control_reporting.py`, `core/services/staff_lifecycle.py`

### `core_accesscontrolpolicystate`

- Application identity: `core.AccessControlPolicyState` in **Access**
- Source of truth: **Yes**
- Retention: Retain while referenced; retire or deactivate instead of deleting governed history.
- Parents: None
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/access_control.py`, `core/services/user_hard_delete.py`
- Used by: `core/services/access_control.py`, `core/services/fresh_database_baseline.py`, `core/services/staff_lifecycle.py`, `core/services/user_hard_delete.py`

### `core_accessgrant`

- Application identity: `core.AccessGrant` in **Access**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.GroupSheetConfiguration`, `core.OperationalLocation`, `core.Product`
- Children: None
- Cross-domain parents: `core.GroupSheetConfiguration`, `core.OperationalLocation`, `core.Product`
- Direct ORM writers: `core/services/product_catalog_full_reset.py`, `core/services/product_deletion.py`, `core/services/staff_access_readiness.py`
- Used by: `core/api/portal_views.py`, `core/management/commands/check_portal_role_separation.py`, `core/services/access_control.py`, `core/services/access_control_reporting.py`, `core/services/access_grant_governance.py`, `core/services/access_policies.py`, `core/services/business_admin.py`, `core/services/fresh_database_baseline.py`, `core/services/jawabu_approvals.py`, `core/services/jawabu_comments.py`, `core/services/location_catalog.py`, `core/services/locations.py`, `core/services/portal_imports.py`, `core/services/product_catalog.py`, `core/services/product_catalog_full_reset.py`, `core/services/product_deletion.py`, `core/services/staff_access_readiness.py`, `core/services/staff_lifecycle.py`, `core/services/tat_notifications.py`, `core/services/tat_production.py`, `core/services/tat_reporting.py`, `core/services/tat_responsibilities.py`, `core/services/tat_setup.py`, `core/services/tat_tracker.py`, `core/services/telegram_identity.py`, `core/services/user_hard_delete.py`, `core/services/workflow_access.py`

### `core_branchservicearea`

- Application identity: `core.BranchServiceArea` in **Catalog**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.OperationalLocation`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: No direct manager mutation found; inspect owning service
- Used by: `core/services/database_catalog.py`, `core/services/location_catalog.py`

### `core_businesscalendarholiday`

- Application identity: `core.BusinessCalendarHoliday` in **Tat**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: None
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/miniapp_settings.py`
- Used by: `core/services/business_calendar.py`, `core/services/miniapp_settings.py`

### `core_capabilityusagedaily`

- Application identity: `core.CapabilityUsageDaily` in **Access**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/access_control.py`
- Used by: `core/services/access_control.py`, `core/services/access_control_reporting.py`, `core/services/user_hard_delete.py`

### `core_caseupdate`

- Application identity: `core.CaseUpdate` in **Complaints**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.ParsedMessage`
- Children: `core.ComplaintCaseEvidence`
- Cross-domain parents: None
- Direct ORM writers: `core/services/case_updates.py`, `core/services/complaint_cases.py`, `core/services/group_reset.py`
- Used by: `core/services/case_updates.py`, `core/services/complaint_cases.py`, `core/services/database_catalog.py`, `core/services/group_reset.py`, `core/services/reporting_relationships.py`

### `core_complaintcasecontrol`

- Application identity: `core.ComplaintCaseControl` in **Complaints**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.ComplaintCategory`, `core.JawabuCustomer`, `core.OperationalLocation`, `core.ParsedMessage`
- Children: `core.ComplaintCaseEvent`
- Cross-domain parents: `core.JawabuCustomer`, `core.OperationalLocation`
- Direct ORM writers: `core/services/complaint_cases.py`, `core/services/group_reset.py`
- Used by: `core/services/complaint_cases.py`, `core/services/complaint_register.py`, `core/services/group_reset.py`

### `core_complaintcaseevent`

- Application identity: `core.ComplaintCaseEvent` in **Complaints**
- Source of truth: **Yes**
- Retention: Retained with the permanent workflow or compliance audit record.
- Parents: `auth.User`, `core.ComplaintCaseControl`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/case_updates.py`, `core/services/complaint_cases.py`, `core/services/group_reset.py`
- Used by: `core/services/case_updates.py`, `core/services/complaint_cases.py`, `core/services/group_reset.py`

### `core_complaintcaseevidence`

- Application identity: `core.ComplaintCaseEvidence` in **Complaints**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.CaseUpdate`, `core.ParsedMessage`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/complaint_cases.py`, `core/services/group_reset.py`
- Used by: `core/services/complaint_cases.py`, `core/services/group_reset.py`, `core/services/reporting_relationships.py`

### `core_complaintcaseimportbatch`

- Application identity: `core.ComplaintCaseImportBatch` in **Complaints**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`
- Children: `core.ComplaintCaseImportItem`
- Cross-domain parents: None
- Direct ORM writers: `core/services/complaint_imports.py`, `core/services/group_reset.py`
- Used by: `core/services/complaint_imports.py`, `core/services/group_reset.py`

### `core_complaintcaseimportitem`

- Application identity: `core.ComplaintCaseImportItem` in **Complaints**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.ComplaintCaseImportBatch`, `core.ParsedMessage`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/complaint_imports.py`, `core/services/group_reset.py`
- Used by: `core/services/complaint_cases.py`, `core/services/complaint_imports.py`, `core/services/group_reset.py`

### `core_complaintcasesequence`

- Application identity: `core.ComplaintCaseSequence` in **Complaints**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: None
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/complaint_cases.py`
- Used by: `core/services/complaint_cases.py`

### `core_complaintcategory`

- Application identity: `core.ComplaintCategory` in **Complaints**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`
- Children: `core.ComplaintCaseControl`, `core.ComplaintCategoryAlias`, `core.ComplaintCategoryAvailability`
- Cross-domain parents: None
- Direct ORM writers: No direct manager mutation found; inspect owning service
- Used by: `core/services/complaint_cases.py`, `core/services/complaint_register.py`, `core/services/database_catalog.py`, `core/services/fresh_database_baseline.py`

### `core_complaintcategoryalias`

- Application identity: `core.ComplaintCategoryAlias` in **Complaints**
- Source of truth: **Yes**
- Retention: Retain while referenced; retire or deactivate instead of deleting governed history.
- Parents: `core.ComplaintCategory`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: No direct manager mutation found; inspect owning service
- Used by: `core/services/complaint_cases.py`

### `core_complaintcategoryavailability`

- Application identity: `core.ComplaintCategoryAvailability` in **Complaints**
- Source of truth: **Yes**
- Retention: Retain while referenced; retire or deactivate instead of deleting governed history.
- Parents: `core.ComplaintCategory`, `core.GroupSheetConfiguration`
- Children: None
- Cross-domain parents: `core.GroupSheetConfiguration`
- Direct ORM writers: No direct manager mutation found; inspect owning service
- Used by: No direct service/API/command reference found

### `core_complianceauditchainstate`

- Application identity: `core.ComplianceAuditChainState` in **Audit**
- Source of truth: **Yes**
- Retention: Retained with the permanent workflow or compliance audit record.
- Parents: None
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/compliance_audit.py`
- Used by: `core/services/compliance_audit.py`

### `core_complianceauditcheckpoint`

- Application identity: `core.ComplianceAuditCheckpoint` in **Audit**
- Source of truth: **No**
- Retention: Retained as compliance evidence; created only by the supervised checkpoint command.
- Parents: None
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/compliance_audit.py`
- Used by: `core/services/compliance_audit.py`, `core/services/database_catalog.py`

### `core_complianceauditevent`

- Application identity: `core.ComplianceAuditEvent` in **Audit**
- Source of truth: **Yes**
- Retention: Permanent; application deletion is prohibited.
- Parents: `auth.User`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/compliance_audit.py`, `core/services/portal_maintenance.py`
- Used by: `core/management/commands/sample_compliance_audit.py`, `core/services/compliance_audit.py`, `core/services/database_catalog.py`, `core/services/origination_god_mode.py`, `core/services/portal_maintenance.py`, `core/services/portal_reporting.py`, `core/services/product_catalog_full_reset.py`, `core/services/product_deletion.py`, `core/services/tat_full_reset.py`, `core/services/user_hard_delete.py`

### `core_deleteduseridentity`

- Application identity: `core.DeletedUserIdentity` in **Platform**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.UserHardDeletionBatch`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/user_hard_delete.py`
- Used by: `core/services/user_hard_delete.py`

### `core_documentphysicalsignoff`

- Application identity: `core.DocumentPhysicalSignoff` in **Platform**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.PaymentDocument`, `core.RequisitionBatch`
- Children: `core.DocumentPhysicalSignoffEvent`
- Cross-domain parents: `core.PaymentDocument`, `core.RequisitionBatch`
- Direct ORM writers: No direct manager mutation found; inspect owning service
- Used by: `core/api/portal_views.py`, `core/services/document_signoffs.py`

### `core_documentphysicalsignoffevent`

- Application identity: `core.DocumentPhysicalSignoffEvent` in **Platform**
- Source of truth: **Yes**
- Retention: Retained with the permanent workflow or compliance audit record.
- Parents: `auth.User`, `core.DocumentPhysicalSignoff`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/document_signoffs.py`
- Used by: `core/services/document_signoffs.py`

### `core_documentsignoffpolicy`

- Application identity: `core.DocumentSignoffPolicy` in **Integration**
- Source of truth: **Yes**
- Retention: Retain while referenced; retire or deactivate instead of deleting governed history.
- Parents: None
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/access_control.py`
- Used by: `core/services/access_control.py`, `core/services/document_signoffs.py`

### `core_durablejobrunnerheartbeat`

- Application identity: `core.DurableJobRunnerHeartbeat` in **Platform**
- Source of truth: **Yes**
- Retention: Service-managed bounded retention; see the owning service and deployment settings.
- Parents: None
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/durable_jobs.py`
- Used by: `core/services/durable_jobs.py`, `core/services/tat_full_reset.py`

### `core_emergencyaccessgrant`

- Application identity: `core.EmergencyAccessGrant` in **Access**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.GroupSheetConfiguration`, `core.Product`
- Children: None
- Cross-domain parents: `core.GroupSheetConfiguration`, `core.Product`
- Direct ORM writers: `core/services/access_control.py`, `core/services/product_catalog_full_reset.py`, `core/services/product_deletion.py`
- Used by: `core/services/access_control.py`, `core/services/access_control_reporting.py`, `core/services/product_catalog.py`, `core/services/product_catalog_full_reset.py`, `core/services/product_deletion.py`, `core/services/staff_access_readiness.py`, `core/services/telegram_identity.py`, `core/services/user_hard_delete.py`

### `core_fcaimportrecord`

- Application identity: `core.FcaImportRecord` in **Jawabu**
- Source of truth: **No**
- Retention: Retained with its FCA import and Jawabu workflow evidence.
- Parents: None
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/fca.py`, `core/services/group_reset.py`
- Used by: `core/api/views.py`, `core/services/database_catalog.py`, `core/services/fca.py`, `core/services/group_reset.py`, `core/services/sheet_publication.py`

### `core_groupsheetconfiguration`

- Application identity: `core.GroupSheetConfiguration` in **Platform**
- Source of truth: **Yes**
- Retention: Retain while referenced; retire or deactivate instead of deleting governed history.
- Parents: None
- Children: `core.AccessGrant`, `core.ComplaintCategoryAvailability`, `core.EmergencyAccessGrant`, `core.LiveSheetRecordChange`, `core.SheetRegisterContract`, `core.StaffTelegramGroupInvitation`, `core.TatActionTask`, `core.TatConfigurationEvent`, `core.TatEscalationRule`, `core.TatGroupExceptionStatus`, `core.TatRepairJob`, `core.TatResponsibilityAssignment`, `core.WorkflowConfigurationChangeRequest`, `core.WorkflowPilotFormulaReadiness`
- Cross-domain parents: None
- Direct ORM writers: `core/services/staff_telegram_onboarding.py`, `core/services/tat_reporting.py`, `core/services/workflow_pilot_purge.py`
- Used by: `core/api/complaint_case_views.py`, `core/management/commands/probe_integrations.py`, `core/management/commands/repair_tat_sheet_duplicates.py`, `core/management/commands/resync_tat_tracker_cases.py`, `core/management/commands/seed_sheet_register_contracts.py`, `core/management/commands/sync_telegram_commands.py`, `core/management/commands/sync_telegram_launchers.py`, `core/services/access_control.py`, `core/services/complaint_register.py`, `core/services/fresh_database_baseline.py`, `core/services/group_config.py`, `core/services/group_reset.py`, `core/services/jawabu.py`, `core/services/jawabu_case360.py`, `core/services/jawabu_pipeline.py`, `core/services/miniapp_settings.py`, `core/services/portal_imports.py`, `core/services/sheet_analyzer.py`, `core/services/sheet_publication.py`, `core/services/spin_credit.py`, `core/services/staff_lifecycle.py`, `core/services/staff_telegram_onboarding.py`, `core/services/sync_governance.py`, `core/services/tat_full_reset.py`, `core/services/tat_notifications.py`, `core/services/tat_production.py`, `core/services/tat_register.py`, `core/services/tat_repair_jobs.py`, `core/services/tat_reporting.py`, `core/services/tat_setup.py`, `core/services/tat_tracker.py`, `core/services/tat_update_dispatch.py`, `core/services/telegram_identity.py`, `core/services/telegram_launchers.py`, `core/services/user_hard_delete.py`, `core/services/workflow_pilot_purge.py`, `core/services/workflow_sla.py`

### `core_integrationcircuitstate`

- Application identity: `core.IntegrationCircuitState` in **Integration**
- Source of truth: **Yes**
- Retention: Retain while referenced; retire or deactivate instead of deleting governed history.
- Parents: None
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/external_resilience.py`
- Used by: `core/services/external_resilience.py`

### `core_integrationoperation`

- Application identity: `core.IntegrationOperation` in **Integration**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/external_resilience.py`
- Used by: `core/api/portal_views.py`, `core/management/commands/probe_integrations.py`, `core/services/complaint_imports.py`, `core/services/external_resilience.py`, `core/services/origination_esign.py`, `core/services/portal_dashboard.py`, `core/services/portal_imports.py`, `core/services/portal_publication.py`, `core/services/tat_setup.py`

### `core_invoiceidentityreview`

- Application identity: `core.InvoiceIdentityReview` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.JawabuFarmerMaster`, `core.ParsedInvoice`
- Children: `core.InvoiceNameChangeItem`
- Cross-domain parents: None
- Direct ORM writers: `core/services/invoice_identity.py`
- Used by: `core/services/invoice_identity.py`, `core/services/portal_dashboard.py`

### `core_invoicenamechangebatch`

- Application identity: `core.InvoiceNameChangeBatch` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.InvoiceNameChangeLetterArtifact`
- Children: `core.InvoiceNameChangeItem`, `core.InvoiceNameChangeLetterArtifact`
- Cross-domain parents: None
- Direct ORM writers: `core/services/invoice_identity.py`
- Used by: `core/api/portal_views.py`, `core/services/invoice_identity.py`, `core/services/invoice_name_change_letters.py`

### `core_invoicenamechangeitem`

- Application identity: `core.InvoiceNameChangeItem` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.InvoiceIdentityReview`, `core.InvoiceNameChangeBatch`, `core.InvoiceNameChangeItem`, `core.JawabuFarmerMaster`, `core.JawabuHouseholdRelationship`, `core.ParsedInvoice`
- Children: `core.InvoiceNameChangeItem`
- Cross-domain parents: None
- Direct ORM writers: `core/services/invoice_identity.py`
- Used by: `core/api/portal_views.py`, `core/services/invoice_identity.py`, `core/services/portal_dashboard.py`

### `core_invoicenamechangeletterartifact`

- Application identity: `core.InvoiceNameChangeLetterArtifact` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.InvoiceNameChangeBatch`, `core.InvoiceNameChangeLetterTemplate`
- Children: `core.InvoiceNameChangeBatch`
- Cross-domain parents: None
- Direct ORM writers: `core/services/invoice_name_change_letters.py`
- Used by: `core/api/portal_views.py`, `core/services/invoice_identity.py`, `core/services/invoice_name_change_letters.py`

### `core_invoicenamechangelettertemplate`

- Application identity: `core.InvoiceNameChangeLetterTemplate` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retain while referenced; retire or deactivate instead of deleting governed history.
- Parents: None
- Children: `core.InvoiceNameChangeLetterArtifact`
- Cross-domain parents: None
- Direct ORM writers: No direct manager mutation found; inspect owning service
- Used by: `core/services/invoice_name_change_letters.py`

### `core_invoiceuploadbatch`

- Application identity: `core.InvoiceUploadBatch` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: None
- Children: `core.ParsedInvoice`
- Cross-domain parents: None
- Direct ORM writers: `core/services/invoice_parser.py`
- Used by: `core/api/portal_views.py`, `core/services/invoice_parser.py`

### `core_jawabuapprovalcondition`

- Application identity: `core.JawabuApprovalCondition` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.JawabuApprovalRecord`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: No direct manager mutation found; inspect owning service
- Used by: `core/api/portal_views.py`, `core/services/jawabu_approvals.py`

### `core_jawabuapprovaldelegation`

- Application identity: `core.JawabuApprovalDelegation` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.Product`
- Children: `core.JawabuApprovalDelegationEvent`, `core.JawabuApprovalRecord`
- Cross-domain parents: `core.Product`
- Direct ORM writers: `core/services/access_control.py`, `core/services/jawabu_approvals.py`, `core/services/product_catalog_full_reset.py`, `core/services/product_deletion.py`, `core/services/user_hard_delete.py`
- Used by: `core/api/portal_views.py`, `core/services/access_control.py`, `core/services/jawabu_approvals.py`, `core/services/product_catalog.py`, `core/services/product_catalog_full_reset.py`, `core/services/product_deletion.py`, `core/services/staff_lifecycle.py`, `core/services/user_hard_delete.py`

### `core_jawabuapprovaldelegationevent`

- Application identity: `core.JawabuApprovalDelegationEvent` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the permanent workflow or compliance audit record.
- Parents: `auth.User`, `core.JawabuApprovalDelegation`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/jawabu_approvals.py`
- Used by: `core/services/jawabu_approvals.py`

### `core_jawabuapprovalrecord`

- Application identity: `core.JawabuApprovalRecord` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.JawabuApprovalDelegation`, `core.JawabuFarmerMaster`, `core.PaymentDocument`
- Children: `core.JawabuApprovalCondition`
- Cross-domain parents: None
- Direct ORM writers: `core/services/jawabu_approvals.py`
- Used by: `core/services/jawabu_approvals.py`

### `core_jawabucasecomment`

- Application identity: `core.JawabuCaseComment` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.JawabuFarmerMaster`, `core.JawabuPipelineEvent`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/jawabu_comments.py`
- Used by: `core/services/jawabu_comments.py`, `core/services/jawabu_master.py`, `core/services/sheet_publication.py`

### `core_jawabucustomer`

- Application identity: `core.JawabuCustomer` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: None
- Children: `core.ComplaintCaseControl`, `core.JawabuCustomerPhoneHistory`, `core.JawabuFarmerMaster`, `core.JawabuRelatedPerson`, `core.LoanOriginationApplication`
- Cross-domain parents: None
- Direct ORM writers: `core/services/invoice_identity.py`, `core/services/jawabu_identity.py`, `core/services/system_export.py`
- Used by: `core/services/complaint_cases.py`, `core/services/invoice_identity.py`, `core/services/jawabu_customer_quality.py`, `core/services/jawabu_data_quality.py`, `core/services/jawabu_identity.py`, `core/services/system_export.py`

### `core_jawabucustomerfieldprovenance`

- Application identity: `core.JawabuCustomerFieldProvenance` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.JawabuFarmerMaster`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/jawabu_customer_quality.py`
- Used by: `core/services/jawabu_customer_quality.py`, `core/services/workflow_timeline.py`

### `core_jawabucustomerphonehistory`

- Application identity: `core.JawabuCustomerPhoneHistory` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the permanent workflow or compliance audit record.
- Parents: `core.JawabuCustomer`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/jawabu_customer_quality.py`
- Used by: `core/services/jawabu_customer_quality.py`

### `core_jawabudataqualityissue`

- Application identity: `core.JawabuDataQualityIssue` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.JawabuFarmerMaster`
- Children: `core.JawabuDataQualityResolution`
- Cross-domain parents: None
- Direct ORM writers: `core/services/jawabu_validation.py`
- Used by: `core/services/jawabu_validation.py`

### `core_jawabudataqualityresolution`

- Application identity: `core.JawabuDataQualityResolution` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.JawabuDataQualityIssue`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: No direct manager mutation found; inspect owning service
- Used by: `core/services/workflow_timeline.py`

### `core_jawabufarmermaster`

- Application identity: `core.JawabuFarmerMaster` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.JawabuCustomer`, `core.OperationalLocation`, `core.Product`, `core.ProductVersion`
- Children: `core.InvoiceIdentityReview`, `core.InvoiceNameChangeItem`, `core.JawabuApprovalRecord`, `core.JawabuCaseComment`, `core.JawabuCustomerFieldProvenance`, `core.JawabuDataQualityIssue`, `core.JawabuHouseholdRelationship`, `core.JawabuMediaAccessEvent`, `core.JawabuPipelineEvent`, `core.MediaAttachment`, `core.ParsedInvoice`, `core.PortalCaseWorkspace`, `core.PortalVoiceTranscriptionAttempt`
- Cross-domain parents: `core.OperationalLocation`, `core.Product`, `core.ProductVersion`
- Direct ORM writers: `core/api/portal_views.py`, `core/services/fca.py`, `core/services/jawabu_master.py`
- Used by: `core/api/portal_views.py`, `core/management/commands/backfill_jbl_schedule_status.py`, `core/management/commands/normalize_jawabu_dates.py`, `core/services/fca.py`, `core/services/fresh_database_baseline.py`, `core/services/group_reset.py`, `core/services/invoice_identity.py`, `core/services/invoice_parser.py`, `core/services/jawabu_approvals.py`, `core/services/jawabu_case360.py`, `core/services/jawabu_comments.py`, `core/services/jawabu_customer_quality.py`, `core/services/jawabu_data_quality.py`, `core/services/jawabu_identity.py`, `core/services/jawabu_master.py`, `core/services/jawabu_media_access.py`, `core/services/jawabu_pipeline.py`, `core/services/jawabu_validation.py`, `core/services/location_catalog.py`, `core/services/payment_documents.py`, `core/services/portal_dashboard.py`, `core/services/portal_publication.py`, `core/services/portal_reporting.py`, `core/services/product_catalog.py`, `core/services/product_deletion.py`, `core/services/reporting_relationships.py`, `core/services/requisition.py`, `core/services/sheet_publication.py`, `core/services/system_export.py`, `core/services/workflow_sla.py`, `core/services/workflow_timeline.py`

### `core_jawabufarmeruploadbatch`

- Application identity: `core.JawabuFarmerUploadBatch` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/group_reset.py`, `core/services/jawabu_master.py`, `core/services/system_export.py`
- Used by: `core/api/portal_views.py`, `core/api/views.py`, `core/management/commands/audit_jawabu_data_quality.py`, `core/services/group_reset.py`, `core/services/jawabu_data_quality.py`, `core/services/jawabu_master.py`, `core/services/portal_imports.py`, `core/services/system_export.py`

### `core_jawabuhouseholdrelationship`

- Application identity: `core.JawabuHouseholdRelationship` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.JawabuFarmerMaster`, `core.JawabuRelatedPerson`
- Children: `core.InvoiceNameChangeItem`
- Cross-domain parents: None
- Direct ORM writers: `core/services/invoice_identity.py`
- Used by: `core/services/invoice_identity.py`

### `core_jawabumediaaccessevent`

- Application identity: `core.JawabuMediaAccessEvent` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the permanent workflow or compliance audit record.
- Parents: `auth.User`, `core.JawabuFarmerMaster`, `core.MediaAttachment`
- Children: None
- Cross-domain parents: `core.MediaAttachment`
- Direct ORM writers: `core/services/jawabu_media_access.py`
- Used by: `core/services/jawabu_media_access.py`

### `core_jawabupipelineevent`

- Application identity: `core.JawabuPipelineEvent` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the permanent workflow or compliance audit record.
- Parents: `auth.User`, `core.JawabuFarmerMaster`
- Children: `core.JawabuCaseComment`
- Cross-domain parents: None
- Direct ORM writers: `core/services/group_reset.py`, `core/services/jawabu_case360.py`
- Used by: `core/api/portal_views.py`, `core/services/group_reset.py`, `core/services/jawabu_case360.py`, `core/services/jawabu_comments.py`, `core/services/jawabu_pipeline.py`, `core/services/portal_dashboard.py`, `core/services/workflow_timeline.py`

### `core_jawaburelatedperson`

- Application identity: `core.JawabuRelatedPerson` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.JawabuCustomer`
- Children: `core.JawabuHouseholdRelationship`
- Cross-domain parents: None
- Direct ORM writers: `core/services/invoice_identity.py`
- Used by: `core/services/invoice_identity.py`

### `core_jawabuvisitrecord`

- Application identity: `core.JawabuVisitRecord` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: None
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/group_reset.py`, `core/services/jawabu.py`
- Used by: `core/services/commands.py`, `core/services/group_reset.py`, `core/services/jawabu.py`

### `core_livesheetrecordchange`

- Application identity: `core.LiveSheetRecordChange` in **Integration**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.GroupSheetConfiguration`
- Children: None
- Cross-domain parents: `core.GroupSheetConfiguration`
- Direct ORM writers: `core/services/group_reset.py`, `core/services/jawabu_pipeline.py`, `core/services/tat_tracker.py`
- Used by: `core/services/group_reset.py`, `core/services/jawabu_pipeline.py`, `core/services/tat_full_reset.py`, `core/services/tat_tracker.py`

### `core_loanoriginationapplication`

- Application identity: `core.LoanOriginationApplication` in **Origination**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.JawabuCustomer`, `core.LoanOriginationApplication`, `core.OperationalLocation`, `core.OriginationProductDefinition`, `core.ProductVersion`
- Children: `core.LoanOriginationApplication`, `core.OriginationApplicationDocument`, `core.OriginationApplicationEvent`, `core.OriginationCommercialException`, `core.OriginationCorrectionRequest`, `core.OriginationReportingValue`, `core.OriginationRequirementEvidence`, `core.OriginationReviewerNotice`, `core.OriginationSigningPackage`
- Cross-domain parents: `core.JawabuCustomer`, `core.OperationalLocation`, `core.ProductVersion`
- Direct ORM writers: `core/services/loan_origination.py`, `core/services/origination_god_mode.py`
- Used by: `core/api/origination_views.py`, `core/services/fresh_database_baseline.py`, `core/services/loan_origination.py`, `core/services/location_catalog.py`, `core/services/origination_commercial_terms.py`, `core/services/origination_consent.py`, `core/services/origination_documents.py`, `core/services/origination_esign.py`, `core/services/origination_evidence.py`, `core/services/origination_fields.py`, `core/services/origination_final_review.py`, `core/services/origination_god_mode.py`, `core/services/product_deletion.py`

### `core_locationconfigurationevent`

- Application identity: `core.LocationConfigurationEvent` in **Catalog**
- Source of truth: **Yes**
- Retention: Retained with the permanent workflow or compliance audit record.
- Parents: `auth.User`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/location_catalog.py`
- Used by: `core/services/location_catalog.py`

### `core_locationmappingissue`

- Application identity: `core.LocationMappingIssue` in **Catalog**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.OperationalLocation`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/location_catalog.py`
- Used by: `core/services/location_catalog.py`

### `core_locationpolicystate`

- Application identity: `core.LocationPolicyState` in **Catalog**
- Source of truth: **Yes**
- Retention: Retain while referenced; retire or deactivate instead of deleting governed history.
- Parents: `auth.User`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/fresh_database_baseline.py`, `core/services/location_catalog.py`
- Used by: `core/services/fresh_database_baseline.py`, `core/services/location_catalog.py`

### `core_mediaattachment`

- Application identity: `core.MediaAttachment` in **Order Approval**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.JawabuFarmerMaster`, `core.OrderApprovalUpdate`
- Children: `core.JawabuMediaAccessEvent`
- Cross-domain parents: `core.JawabuFarmerMaster`
- Direct ORM writers: `core/services/group_reset.py`, `core/services/jawabu_pipeline.py`, `core/services/order_approval.py`
- Used by: `core/api/portal_views.py`, `core/services/commands.py`, `core/services/database_catalog.py`, `core/services/group_reset.py`, `core/services/jawabu_approvals.py`, `core/services/jawabu_media_access.py`, `core/services/jawabu_pipeline.py`, `core/services/order_approval.py`, `core/services/portal_reporting.py`, `core/services/workflow_timeline.py`

### `core_miniappdiagnosticdailyaggregate`

- Application identity: `core.MiniAppDiagnosticDailyAggregate` in **Platform**
- Source of truth: **No**
- Retention: Retention is configured by MINIAPP_DIAGNOSTICS_AGGREGATE_RETENTION_DAYS.
- Parents: None
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/miniapp_diagnostics.py`
- Used by: `core/services/database_catalog.py`, `core/services/miniapp_diagnostics.py`

### `core_miniappdiagnosticevent`

- Application identity: `core.MiniAppDiagnosticEvent` in **Platform**
- Source of truth: **No**
- Retention: Deleted with expired raw diagnostic sessions after aggregation.
- Parents: `core.MiniAppDiagnosticSession`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/miniapp_diagnostics.py`
- Used by: `core/services/database_catalog.py`, `core/services/miniapp_diagnostics.py`

### `core_miniappdiagnosticsession`

- Application identity: `core.MiniAppDiagnosticSession` in **Platform**
- Source of truth: **No**
- Retention: Raw retention is configured by MINIAPP_DIAGNOSTICS_RAW_RETENTION_DAYS, then aggregated.
- Parents: `auth.User`
- Children: `core.MiniAppDiagnosticEvent`
- Cross-domain parents: None
- Direct ORM writers: `core/services/miniapp_diagnostics.py`
- Used by: `core/api/miniapp_diagnostic_views.py`, `core/services/database_catalog.py`, `core/services/miniapp_diagnostics.py`, `core/services/user_hard_delete.py`

### `core_miniappdraft`

- Application identity: `core.MiniAppDraft` in **Platform**
- Source of truth: **Yes**
- Retention: Service-managed bounded retention; see the owning service and deployment settings.
- Parents: `auth.User`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/miniapp_drafts.py`
- Used by: `core/services/miniapp_drafts.py`, `core/services/user_hard_delete.py`

### `core_miniapplegacywritedailyaggregate`

- Application identity: `core.MiniAppLegacyWriteDailyAggregate` in **Platform**
- Source of truth: **No**
- Retention: Bounded by the idempotency readiness observation window and operational policy.
- Parents: None
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/miniapp_idempotency.py`
- Used by: `core/services/database_catalog.py`, `core/services/miniapp_idempotency.py`

### `core_operationallocation`

- Application identity: `core.OperationalLocation` in **Catalog**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.OperationalLocation`
- Children: `core.AccessGrant`, `core.BranchServiceArea`, `core.ComplaintCaseControl`, `core.JawabuFarmerMaster`, `core.LoanOriginationApplication`, `core.LocationMappingIssue`, `core.OperationalLocation`, `core.OperationalLocationAlias`, `core.OrderApprovalUpdate`, `core.OriginationStampAsset`, `core.ProductAvailability`
- Cross-domain parents: None
- Direct ORM writers: `core/services/fresh_database_baseline.py`
- Used by: `core/api/origination_views.py`, `core/services/complaint_cases.py`, `core/services/database_catalog.py`, `core/services/fresh_database_baseline.py`, `core/services/jawabu_pipeline.py`, `core/services/location_catalog.py`, `core/services/locations.py`, `core/services/product_availability.py`, `core/services/spin_credit.py`, `core/services/tat_tracker.py`, `core/services/workflow_catalog.py`

### `core_operationallocationalias`

- Application identity: `core.OperationalLocationAlias` in **Catalog**
- Source of truth: **Yes**
- Retention: Retain while referenced; retire or deactivate instead of deleting governed history.
- Parents: `auth.User`, `core.OperationalLocation`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: No direct manager mutation found; inspect owning service
- Used by: `core/services/location_catalog.py`

### `core_orderapprovalupdate`

- Application identity: `core.OrderApprovalUpdate` in **Order Approval**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.OperationalLocation`
- Children: `core.MediaAttachment`
- Cross-domain parents: `core.OperationalLocation`
- Direct ORM writers: `core/services/group_reset.py`, `core/services/order_approval.py`
- Used by: `core/services/commands.py`, `core/services/group_reset.py`, `core/services/location_catalog.py`, `core/services/order_approval.py`

### `core_originationapplicationdocument`

- Application identity: `core.OriginationApplicationDocument` in **Origination**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.LoanOriginationApplication`, `core.OriginationDocumentTemplate`, `core.OriginationProductDocumentAssignment`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/origination_documents.py`
- Used by: `core/services/origination_documents.py`, `core/services/origination_fields.py`, `core/services/origination_god_mode.py`

### `core_originationapplicationevent`

- Application identity: `core.OriginationApplicationEvent` in **Origination**
- Source of truth: **Yes**
- Retention: Retained with the permanent workflow or compliance audit record.
- Parents: `auth.User`, `core.LoanOriginationApplication`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/loan_origination.py`
- Used by: `core/services/loan_origination.py`, `core/services/origination_god_mode.py`

### `core_originationcommercialexception`

- Application identity: `core.OriginationCommercialException` in **Origination**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.LoanOriginationApplication`, `core.ProductVersion`
- Children: None
- Cross-domain parents: `core.ProductVersion`
- Direct ORM writers: `core/services/origination_commercial_terms.py`
- Used by: `core/services/origination_commercial_terms.py`, `core/services/origination_god_mode.py`, `core/services/product_deletion.py`

### `core_originationconsentpolicyversion`

- Application identity: `core.OriginationConsentPolicyVersion` in **Origination**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`
- Children: `core.OriginationDocumentTemplate`, `core.OriginationSigningPackage`
- Cross-domain parents: None
- Direct ORM writers: No direct manager mutation found; inspect owning service
- Used by: `core/services/origination_consent.py`, `core/services/origination_god_mode.py`

### `core_originationcorrectionitem`

- Application identity: `core.OriginationCorrectionItem` in **Origination**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.OriginationCorrectionRequest`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/loan_origination.py`, `core/services/origination_final_review.py`
- Used by: `core/services/loan_origination.py`, `core/services/origination_final_review.py`, `core/services/origination_god_mode.py`

### `core_originationcorrectionrequest`

- Application identity: `core.OriginationCorrectionRequest` in **Origination**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.LoanOriginationApplication`
- Children: `core.OriginationCorrectionItem`
- Cross-domain parents: None
- Direct ORM writers: `core/services/loan_origination.py`, `core/services/origination_final_review.py`
- Used by: `core/services/loan_origination.py`, `core/services/origination_final_review.py`, `core/services/origination_god_mode.py`

### `core_originationdatafield`

- Application identity: `core.OriginationDataField` in **Origination**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.OriginationDataField`
- Children: `core.OriginationDataField`, `core.OriginationDataFieldEvent`, `core.OriginationFieldReviewIssue`, `core.OriginationReportingValue`
- Cross-domain parents: None
- Direct ORM writers: `core/services/origination_commercial_terms.py`, `core/services/origination_fields.py`, `core/services/origination_main_laf_seeds.py`
- Used by: `core/management/commands/seed_origination_packet_demo.py`, `core/management/commands/upgrade_origination_commercial_contract.py`, `core/services/generic_jawabu_laf_seed.py`, `core/services/invoice_finance_origination_seed.py`, `core/services/origination_commercial_terms.py`, `core/services/origination_fields.py`, `core/services/origination_god_mode.py`, `core/services/origination_main_laf_seeds.py`, `core/services/origination_templates.py`

### `core_originationdatafieldevent`

- Application identity: `core.OriginationDataFieldEvent` in **Origination**
- Source of truth: **Yes**
- Retention: Retained with the permanent workflow or compliance audit record.
- Parents: `auth.User`, `core.OriginationDataField`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/generic_jawabu_laf_seed.py`, `core/services/invoice_finance_origination_seed.py`, `core/services/origination_commercial_terms.py`, `core/services/origination_fields.py`, `core/services/origination_main_laf_seeds.py`
- Used by: `core/services/generic_jawabu_laf_seed.py`, `core/services/invoice_finance_origination_seed.py`, `core/services/origination_commercial_terms.py`, `core/services/origination_fields.py`, `core/services/origination_god_mode.py`, `core/services/origination_main_laf_seeds.py`

### `core_originationdocumentproducteligibility`

- Application identity: `core.OriginationDocumentProductEligibility` in **Origination**
- Source of truth: **Yes**
- Retention: Retained while the catalogue document or product history requires it.
- Parents: `auth.User`, `core.OriginationDocumentTemplate`, `core.Product`
- Children: None
- Cross-domain parents: `core.Product`
- Direct ORM writers: `core/services/origination_god_mode.py`, `core/services/origination_main_laf_seeds.py`, `core/services/origination_templates.py`, `core/services/product_catalog_full_reset.py`, `core/services/product_deletion.py`
- Used by: `core/services/database_catalog.py`, `core/services/origination_document_catalogue.py`, `core/services/origination_god_mode.py`, `core/services/origination_main_laf_seeds.py`, `core/services/origination_templates.py`, `core/services/product_catalog_full_reset.py`, `core/services/product_deletion.py`

### `core_originationdocumenttemplate`

- Application identity: `core.OriginationDocumentTemplate` in **Origination**
- Source of truth: **Yes**
- Retention: Retain while referenced; retire or deactivate instead of deleting governed history.
- Parents: `auth.User`, `core.OriginationConsentPolicyVersion`, `core.OriginationProductDefinition`, `core.OriginationTemplateConfigurationRevision`
- Children: `core.OriginationApplicationDocument`, `core.OriginationDocumentProductEligibility`, `core.OriginationDocumentTemplateEvent`, `core.OriginationProductDocumentAssignment`, `core.OriginationTemplateConfigurationRevision`
- Cross-domain parents: None
- Direct ORM writers: `core/management/commands/seed_origination_packet_demo.py`, `core/services/generic_jawabu_laf_seed.py`, `core/services/origination_god_mode.py`, `core/services/origination_main_laf_seeds.py`, `core/services/origination_templates.py`, `core/services/product_deletion.py`
- Used by: `core/management/commands/seed_origination_packet_demo.py`, `core/management/commands/upgrade_origination_commercial_contract.py`, `core/services/generic_jawabu_laf_seed.py`, `core/services/invoice_finance_origination_seed.py`, `core/services/loan_origination.py`, `core/services/origination_consent.py`, `core/services/origination_document_catalogue.py`, `core/services/origination_documents.py`, `core/services/origination_fields.py`, `core/services/origination_god_mode.py`, `core/services/origination_main_laf_seeds.py`, `core/services/origination_setup.py`, `core/services/origination_templates.py`, `core/services/product_deletion.py`

### `core_originationdocumenttemplateevent`

- Application identity: `core.OriginationDocumentTemplateEvent` in **Origination**
- Source of truth: **Yes**
- Retention: Retained with the permanent workflow or compliance audit record.
- Parents: `auth.User`, `core.OriginationDocumentTemplate`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/generic_jawabu_laf_seed.py`, `core/services/invoice_finance_origination_seed.py`, `core/services/origination_fields.py`, `core/services/origination_god_mode.py`, `core/services/origination_main_laf_seeds.py`, `core/services/origination_templates.py`
- Used by: `core/services/generic_jawabu_laf_seed.py`, `core/services/invoice_finance_origination_seed.py`, `core/services/origination_fields.py`, `core/services/origination_god_mode.py`, `core/services/origination_main_laf_seeds.py`, `core/services/origination_templates.py`, `core/services/product_deletion.py`

### `core_originationfieldreviewissue`

- Application identity: `core.OriginationFieldReviewIssue` in **Origination**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.OriginationDataField`, `core.OriginationProductDefinition`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/origination_fields.py`, `core/services/origination_god_mode.py`
- Used by: `core/services/origination_fields.py`, `core/services/origination_god_mode.py`, `core/services/product_deletion.py`

### `core_originationotpchallenge`

- Application identity: `core.OriginationOtpChallenge` in **Origination**
- Source of truth: **Yes**
- Retention: Service-managed bounded retention; see the owning service and deployment settings.
- Parents: `core.OriginationSignerSession`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/origination_esign.py`
- Used by: `core/services/origination_esign.py`, `core/services/origination_god_mode.py`

### `core_originationproductdefinition`

- Application identity: `core.OriginationProductDefinition` in **Origination**
- Source of truth: **Yes**
- Retention: Retain while referenced; retire or deactivate instead of deleting governed history.
- Parents: `auth.User`, `core.OriginationProductDefinition`, `core.ProductVersion`
- Children: `core.LoanOriginationApplication`, `core.OriginationDocumentTemplate`, `core.OriginationFieldReviewIssue`, `core.OriginationProductDefinition`, `core.OriginationProductDefinitionEvent`, `core.OriginationProductDocumentAssignment`
- Cross-domain parents: `core.ProductVersion`
- Direct ORM writers: `core/management/commands/seed_origination_packet_demo.py`, `core/services/invoice_finance_origination_seed.py`, `core/services/origination_god_mode.py`, `core/services/origination_setup.py`, `core/services/origination_templates.py`
- Used by: `core/api/origination_views.py`, `core/management/commands/seed_origination_packet_demo.py`, `core/management/commands/upgrade_origination_commercial_contract.py`, `core/services/invoice_finance_origination_seed.py`, `core/services/loan_origination.py`, `core/services/origination_document_catalogue.py`, `core/services/origination_documents.py`, `core/services/origination_fields.py`, `core/services/origination_god_mode.py`, `core/services/origination_setup.py`, `core/services/origination_templates.py`, `core/services/product_deletion.py`

### `core_originationproductdefinitionevent`

- Application identity: `core.OriginationProductDefinitionEvent` in **Origination**
- Source of truth: **Yes**
- Retention: Retained with the permanent workflow or compliance audit record.
- Parents: `auth.User`, `core.OriginationProductDefinition`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/management/commands/upgrade_origination_commercial_contract.py`, `core/services/invoice_finance_origination_seed.py`, `core/services/origination_fields.py`, `core/services/origination_god_mode.py`, `core/services/origination_setup.py`, `core/services/origination_templates.py`
- Used by: `core/management/commands/upgrade_origination_commercial_contract.py`, `core/services/invoice_finance_origination_seed.py`, `core/services/origination_fields.py`, `core/services/origination_god_mode.py`, `core/services/origination_setup.py`, `core/services/origination_templates.py`, `core/services/product_deletion.py`

### `core_originationproductdocumentassignment`

- Application identity: `core.OriginationProductDocumentAssignment` in **Origination**
- Source of truth: **Yes**
- Retention: Retained for historical product-definition and application compatibility.
- Parents: `auth.User`, `core.OriginationDocumentTemplate`, `core.OriginationProductDefinition`
- Children: `core.OriginationApplicationDocument`
- Cross-domain parents: None
- Direct ORM writers: `core/management/commands/seed_origination_packet_demo.py`, `core/services/origination_god_mode.py`, `core/services/origination_templates.py`
- Used by: `core/management/commands/seed_origination_packet_demo.py`, `core/services/database_catalog.py`, `core/services/origination_documents.py`, `core/services/origination_god_mode.py`, `core/services/origination_templates.py`, `core/services/product_deletion.py`

### `core_originationreportingvalue`

- Application identity: `core.OriginationReportingValue` in **Origination**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.LoanOriginationApplication`, `core.OriginationDataField`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/origination_fields.py`, `core/services/origination_god_mode.py`
- Used by: `core/services/origination_fields.py`, `core/services/origination_god_mode.py`

### `core_originationrequirementevidence`

- Application identity: `core.OriginationRequirementEvidence` in **Origination**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.LoanOriginationApplication`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/origination_evidence.py`, `core/services/origination_god_mode.py`
- Used by: `core/api/origination_views.py`, `core/services/origination_evidence.py`, `core/services/origination_god_mode.py`

### `core_originationreviewernotice`

- Application identity: `core.OriginationReviewerNotice` in **Origination**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.LoanOriginationApplication`, `core.OriginationSigningPackage`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/loan_origination.py`
- Used by: `core/api/origination_views.py`, `core/services/loan_origination.py`, `core/services/origination_god_mode.py`

### `core_originationsignersession`

- Application identity: `core.OriginationSignerSession` in **Origination**
- Source of truth: **Yes**
- Retention: Service-managed bounded retention; see the owning service and deployment settings.
- Parents: `auth.User`, `core.OriginationSigningPackage`
- Children: `core.OriginationOtpChallenge`, `core.OriginationSigningAction`, `core.OriginationSigningRequestEvent`
- Cross-domain parents: None
- Direct ORM writers: `core/services/origination_esign.py`
- Used by: `core/api/origination_views.py`, `core/services/origination_esign.py`, `core/services/origination_god_mode.py`

### `core_originationsigningaction`

- Application identity: `core.OriginationSigningAction` in **Origination**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.OriginationSignerSession`, `core.OriginationSigningAction`, `core.OriginationSigningPackage`, `core.OriginationStampAsset`
- Children: `core.OriginationSigningAction`, `core.OriginationSigningActionInvalidation`
- Cross-domain parents: None
- Direct ORM writers: `core/services/origination_esign.py`, `core/services/origination_signing.py`
- Used by: `core/services/origination_esign.py`, `core/services/origination_final_review.py`, `core/services/origination_god_mode.py`, `core/services/origination_signing.py`

### `core_originationsigningactioninvalidation`

- Application identity: `core.OriginationSigningActionInvalidation` in **Origination**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.OriginationSigningAction`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/origination_final_review.py`
- Used by: `core/services/origination_final_review.py`, `core/services/origination_god_mode.py`

### `core_originationsigningpackage`

- Application identity: `core.OriginationSigningPackage` in **Origination**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.LoanOriginationApplication`, `core.OriginationConsentPolicyVersion`
- Children: `core.OriginationReviewerNotice`, `core.OriginationSignerSession`, `core.OriginationSigningAction`
- Cross-domain parents: None
- Direct ORM writers: `core/services/origination_esign.py`
- Used by: `core/api/origination_views.py`, `core/management/commands/repair_origination_frozen_packet.py`, `core/services/loan_origination.py`, `core/services/origination_esign.py`, `core/services/origination_evidence.py`, `core/services/origination_final_review.py`, `core/services/origination_god_mode.py`, `core/services/origination_signing.py`

### `core_originationsigningrequestevent`

- Application identity: `core.OriginationSigningRequestEvent` in **Origination**
- Source of truth: **Yes**
- Retention: Retained with the permanent workflow or compliance audit record.
- Parents: `core.OriginationSignerSession`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/origination_esign.py`
- Used by: `core/services/origination_esign.py`, `core/services/origination_god_mode.py`

### `core_originationstampasset`

- Application identity: `core.OriginationStampAsset` in **Origination**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.OperationalLocation`
- Children: `core.OriginationSigningAction`
- Cross-domain parents: `core.OperationalLocation`
- Direct ORM writers: `core/services/origination_god_mode.py`
- Used by: `core/services/origination_esign.py`, `core/services/origination_god_mode.py`, `core/services/origination_signing.py`

### `core_originationtemplateconfigurationrevision`

- Application identity: `core.OriginationTemplateConfigurationRevision` in **Origination**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.OriginationDocumentTemplate`
- Children: `core.OriginationDocumentTemplate`
- Cross-domain parents: None
- Direct ORM writers: `core/services/origination_god_mode.py`, `core/services/origination_templates.py`
- Used by: `core/services/origination_god_mode.py`, `core/services/origination_templates.py`, `core/services/product_deletion.py`

### `core_parsedinvoice`

- Application identity: `core.ParsedInvoice` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.InvoiceUploadBatch`, `core.JawabuFarmerMaster`
- Children: `core.InvoiceIdentityReview`, `core.InvoiceNameChangeItem`, `core.ParsedInvoiceEvent`
- Cross-domain parents: None
- Direct ORM writers: `core/services/invoice_parser.py`
- Used by: `core/api/portal_views.py`, `core/services/database_catalog.py`, `core/services/invoice_identity.py`, `core/services/invoice_parser.py`, `core/services/jawabu_case360.py`, `core/services/payment_documents.py`, `core/services/portal_reporting.py`, `core/services/workflow_timeline.py`

### `core_parsedinvoiceevent`

- Application identity: `core.ParsedInvoiceEvent` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the permanent workflow or compliance audit record.
- Parents: `core.ParsedInvoice`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/invoice_parser.py`
- Used by: `core/services/invoice_parser.py`

### `core_parsedmessage`

- Application identity: `core.ParsedMessage` in **Complaints**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.ProcessedMessage`
- Children: `core.CaseUpdate`, `core.ComplaintCaseControl`, `core.ComplaintCaseEvidence`, `core.ComplaintCaseImportItem`
- Cross-domain parents: None
- Direct ORM writers: `core/api/views.py`, `core/services/complaint_cases.py`, `core/services/group_reset.py`, `core/services/sheet_sync.py`, `core/services/sheets.py`, `core/services/storage.py`
- Used by: `core/api/views.py`, `core/services/case_updates.py`, `core/services/commands.py`, `core/services/complaint_cases.py`, `core/services/complaint_imports.py`, `core/services/complaint_register.py`, `core/services/database_catalog.py`, `core/services/fresh_database_baseline.py`, `core/services/group_reset.py`, `core/services/reporting_relationships.py`, `core/services/sheet_publication.py`, `core/services/sheet_sync.py`, `core/services/sheets.py`, `core/services/storage.py`, `core/services/workflow_catalog.py`

### `core_paymentdocument`

- Application identity: `core.PaymentDocument` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: None
- Children: `core.DocumentPhysicalSignoff`, `core.JawabuApprovalRecord`
- Cross-domain parents: None
- Direct ORM writers: `core/services/payment_documents.py`
- Used by: `core/api/portal_views.py`, `core/services/database_catalog.py`, `core/services/document_signoffs.py`, `core/services/jawabu_case360.py`, `core/services/payment_documents.py`, `core/services/portal_health.py`, `core/services/portal_reconciliation.py`, `core/services/workflow_timeline.py`

### `core_paymentdocumenttemplate`

- Application identity: `core.PaymentDocumentTemplate` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retain while referenced; retire or deactivate instead of deleting governed history.
- Parents: None
- Children: None
- Cross-domain parents: None
- Direct ORM writers: No direct manager mutation found; inspect owning service
- Used by: `core/services/payment_documents.py`, `core/services/portal_health.py`

### `core_portalcaseworkspace`

- Application identity: `core.PortalCaseWorkspace` in **Platform**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.JawabuFarmerMaster`
- Children: None
- Cross-domain parents: `core.JawabuFarmerMaster`
- Direct ORM writers: `core/services/portal_workspace.py`
- Used by: `core/api/portal_views.py`, `core/services/portal_workspace.py`, `core/services/user_hard_delete.py`

### `core_portalmaintenancestate`

- Application identity: `core.PortalMaintenanceState` in **Platform**
- Source of truth: **Yes**
- Retention: Retain while referenced; retire or deactivate instead of deleting governed history.
- Parents: `auth.User`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/portal_maintenance.py`
- Used by: `core/services/portal_maintenance.py`

### `core_portalreportchart`

- Application identity: `core.PortalReportChart` in **Platform**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.PortalReportDefinition`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/portal_reporting.py`
- Used by: `core/services/portal_reporting.py`

### `core_portalreportdefinition`

- Application identity: `core.PortalReportDefinition` in **Platform**
- Source of truth: **Yes**
- Retention: Retain while referenced; retire or deactivate instead of deleting governed history.
- Parents: `auth.User`
- Children: `core.PortalReportChart`
- Cross-domain parents: None
- Direct ORM writers: `core/services/portal_reporting.py`
- Used by: `core/api/portal_views.py`, `core/services/portal_reporting.py`

### `core_portalsavedview`

- Application identity: `core.PortalSavedView` in **Platform**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/portal_workspace.py`
- Used by: `core/services/portal_workspace.py`, `core/services/user_hard_delete.py`

### `core_portalvoicetranscriptionattempt`

- Application identity: `core.PortalVoiceTranscriptionAttempt` in **Platform**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.JawabuFarmerMaster`, `core.PortalVoiceTranscriptionAttempt`
- Children: `core.PortalVoiceTranscriptionAttempt`
- Cross-domain parents: `core.JawabuFarmerMaster`
- Direct ORM writers: `core/services/portal_voice.py`
- Used by: `core/api/portal_views.py`, `core/services/portal_voice.py`

### `core_processedmessage`

- Application identity: `core.ProcessedMessage` in **Complaints**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.RawMessage`
- Children: `core.ParsedMessage`
- Cross-domain parents: None
- Direct ORM writers: `core/services/complaint_cases.py`, `core/services/deduplication.py`, `core/services/group_reset.py`, `core/services/sheet_sync.py`
- Used by: `core/services/complaint_cases.py`, `core/services/database_catalog.py`, `core/services/deduplication.py`, `core/services/group_reset.py`, `core/services/reporting_relationships.py`, `core/services/sheet_sync.py`, `core/services/storage.py`

### `core_product`

- Application identity: `core.Product` in **Catalog**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: None
- Children: `core.AccessGrant`, `core.EmergencyAccessGrant`, `core.JawabuApprovalDelegation`, `core.JawabuFarmerMaster`, `core.OriginationDocumentProductEligibility`, `core.ProductAlias`, `core.ProductAvailability`, `core.ProductMappingIssue`, `core.ProductVersion`, `core.SpinCreditRequest`, `core.TatRepairJob`, `core.TatTrackerCase`, `core.WorkflowTatDailyMetric`
- Cross-domain parents: None
- Direct ORM writers: `core/services/product_catalog_full_reset.py`
- Used by: `core/api/views.py`, `core/services/access_policies.py`, `core/services/database_catalog.py`, `core/services/fresh_database_baseline.py`, `core/services/generic_jawabu_laf_seed.py`, `core/services/invoice_finance_origination_seed.py`, `core/services/jawabu_customer_quality.py`, `core/services/jawabu_pipeline.py`, `core/services/loan_origination.py`, `core/services/origination_fields.py`, `core/services/origination_god_mode.py`, `core/services/origination_main_laf_seeds.py`, `core/services/origination_setup.py`, `core/services/origination_templates.py`, `core/services/origination_terminology.py`, `core/services/product_availability.py`, `core/services/product_catalog.py`, `core/services/product_catalog_full_reset.py`, `core/services/product_deletion.py`, `core/services/sheet_publication.py`, `core/services/spin_credit.py`, `core/services/system_export.py`, `core/services/tat_register.py`, `core/services/tat_reporting.py`, `core/services/tat_tracker.py`, `core/services/workflow_catalog.py`

### `core_productalias`

- Application identity: `core.ProductAlias` in **Catalog**
- Source of truth: **Yes**
- Retention: Retain while referenced; retire or deactivate instead of deleting governed history.
- Parents: `core.Product`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/product_catalog.py`
- Used by: `core/services/product_catalog.py`

### `core_productavailability`

- Application identity: `core.ProductAvailability` in **Catalog**
- Source of truth: **Yes**
- Retention: Retain while referenced; retire or deactivate instead of deleting governed history.
- Parents: `core.OperationalLocation`, `core.Product`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/product_availability.py`, `core/services/product_catalog_full_reset.py`
- Used by: `core/services/product_availability.py`, `core/services/product_catalog.py`, `core/services/product_catalog_full_reset.py`, `core/services/product_deletion.py`, `core/services/tat_full_reset.py`

### `core_productcustomattribute`

- Application identity: `core.ProductCustomAttribute` in **Catalog**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.ProductVersion`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: No direct manager mutation found; inspect owning service
- Used by: `core/services/product_catalog.py`, `core/services/product_deletion.py`

### `core_productfee`

- Application identity: `core.ProductFee` in **Catalog**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.ProductVersion`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: No direct manager mutation found; inspect owning service
- Used by: `core/services/origination_commercial_terms.py`, `core/services/product_deletion.py`, `core/services/product_quotes.py`

### `core_productionreleaseaudit`

- Application identity: `core.ProductionReleaseAudit` in **Catalog**
- Source of truth: **Yes**
- Retention: Retained with the permanent workflow or compliance audit record.
- Parents: None
- Children: None
- Cross-domain parents: None
- Direct ORM writers: No direct manager mutation found; inspect owning service
- Used by: `core/management/commands/release_production.py`, `core/services/production_release.py`

### `core_productmappingissue`

- Application identity: `core.ProductMappingIssue` in **Catalog**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.Product`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/product_catalog.py`, `core/services/product_catalog_full_reset.py`, `core/services/product_deletion.py`
- Used by: `core/services/product_catalog.py`, `core/services/product_catalog_full_reset.py`, `core/services/product_deletion.py`

### `core_productrequirement`

- Application identity: `core.ProductRequirement` in **Catalog**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.ProductVersion`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: No direct manager mutation found; inspect owning service
- Used by: `core/services/product_catalog.py`, `core/services/product_deletion.py`

### `core_producttatconfiguration`

- Application identity: `core.ProductTatConfiguration` in **Catalog**
- Source of truth: **Yes**
- Retention: Retain while referenced; retire or deactivate instead of deleting governed history.
- Parents: `core.ProductVersion`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: No direct manager mutation found; inspect owning service
- Used by: `core/services/product_deletion.py`, `core/services/tat_configuration.py`, `core/services/tat_full_reset.py`, `core/services/tat_setup.py`, `core/services/tat_tracker.py`

### `core_productversion`

- Application identity: `core.ProductVersion` in **Catalog**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.Product`, `core.ProductVersion`
- Children: `core.JawabuFarmerMaster`, `core.LoanOriginationApplication`, `core.OriginationCommercialException`, `core.OriginationProductDefinition`, `core.ProductCustomAttribute`, `core.ProductFee`, `core.ProductRequirement`, `core.ProductTatConfiguration`, `core.ProductVersion`, `core.ProductVersionEvent`, `core.SpinCreditRequest`, `core.TatTrackerCase`
- Cross-domain parents: None
- Direct ORM writers: `core/services/product_catalog.py`, `core/services/product_deletion.py`
- Used by: `core/services/invoice_finance_origination_seed.py`, `core/services/origination_commercial_terms.py`, `core/services/origination_main_laf_seeds.py`, `core/services/origination_setup.py`, `core/services/product_catalog.py`, `core/services/product_catalog_full_reset.py`, `core/services/product_deletion.py`, `core/services/product_quotes.py`, `core/services/tat_configuration.py`, `core/services/tat_setup.py`, `core/services/tat_tracker.py`

### `core_productversionevent`

- Application identity: `core.ProductVersionEvent` in **Catalog**
- Source of truth: **Yes**
- Retention: Retained with the permanent workflow or compliance audit record.
- Parents: `auth.User`, `core.ProductVersion`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/product_catalog.py`, `core/services/product_deletion.py`
- Used by: `core/services/origination_setup.py`, `core/services/product_catalog.py`, `core/services/product_deletion.py`

### `core_publicendpointthrottlebucket`

- Application identity: `core.PublicEndpointThrottleBucket` in **Platform**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: None
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/request_throttling.py`
- Used by: `core/services/request_throttling.py`

### `core_rawmessage`

- Application identity: `core.RawMessage` in **Complaints**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: None
- Children: `core.ProcessedMessage`
- Cross-domain parents: None
- Direct ORM writers: `core/services/complaint_cases.py`, `core/services/group_reset.py`, `core/services/sheet_sync.py`, `core/services/storage.py`
- Used by: `core/services/complaint_cases.py`, `core/services/database_catalog.py`, `core/services/deduplication.py`, `core/services/group_reset.py`, `core/services/reporting_relationships.py`, `core/services/sheet_sync.py`, `core/services/storage.py`

### `core_requisitionbatch`

- Application identity: `core.RequisitionBatch` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: None
- Children: `core.DocumentPhysicalSignoff`
- Cross-domain parents: None
- Direct ORM writers: `core/api/portal_views.py`
- Used by: `core/api/portal_views.py`, `core/services/document_signoffs.py`, `core/services/invoice_parser.py`, `core/services/jawabu_case360.py`, `core/services/portal_health.py`, `core/services/portal_reconciliation.py`, `core/services/workflow_timeline.py`

### `core_requisitiontemplate`

- Application identity: `core.RequisitionTemplate` in **Jawabu**
- Source of truth: **Yes**
- Retention: Retain while referenced; retire or deactivate instead of deleting governed history.
- Parents: None
- Children: None
- Cross-domain parents: None
- Direct ORM writers: No direct manager mutation found; inspect owning service
- Used by: `core/services/portal_health.py`, `core/services/requisition.py`

### `core_sheetregistercontract`

- Application identity: `core.SheetRegisterContract` in **Integration**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.GroupSheetConfiguration`
- Children: `core.SheetSyncAuditSnapshot`
- Cross-domain parents: `core.GroupSheetConfiguration`
- Direct ORM writers: No direct manager mutation found; inspect owning service
- Used by: `core/management/commands/seed_sheet_register_contracts.py`, `core/services/sync_governance.py`, `core/services/tat_production.py`, `core/services/tat_setup.py`

### `core_sheetsyncauditsnapshot`

- Application identity: `core.SheetSyncAuditSnapshot` in **Integration**
- Source of truth: **Yes**
- Retention: Retained with the permanent workflow or compliance audit record.
- Parents: `core.SheetRegisterContract`
- Children: `core.SheetSyncDiscrepancy`
- Cross-domain parents: None
- Direct ORM writers: `core/services/sync_governance.py`
- Used by: `core/services/sync_governance.py`, `core/services/tat_setup.py`

### `core_sheetsyncdiscrepancy`

- Application identity: `core.SheetSyncDiscrepancy` in **Integration**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.SheetSyncAuditSnapshot`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/sync_governance.py`
- Used by: `core/services/sync_governance.py`

### `core_spinbatchreviewitem`

- Application identity: `core.SpinBatchReviewItem` in **Spin**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.SpinCreditRequest`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/spin_credit.py`, `core/services/workflow_pilot_purge.py`
- Used by: `core/api/views.py`, `core/services/spin_credit.py`, `core/services/workflow_data_mode.py`, `core/services/workflow_pilot_purge.py`

### `core_spincreditrequest`

- Application identity: `core.SpinCreditRequest` in **Spin**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.Product`, `core.ProductVersion`
- Children: `core.SpinBatchReviewItem`
- Cross-domain parents: `core.Product`, `core.ProductVersion`
- Direct ORM writers: `core/services/spin_credit.py`, `core/services/workflow_pilot_purge.py`
- Used by: `core/api/portal_views.py`, `core/api/views.py`, `core/services/fresh_database_baseline.py`, `core/services/group_reset.py`, `core/services/product_catalog.py`, `core/services/product_deletion.py`, `core/services/reporting_relationships.py`, `core/services/sheet_publication.py`, `core/services/spin_credit.py`, `core/services/workflow_data_mode.py`, `core/services/workflow_pilot_purge.py`

### `core_spinrequestsequence`

- Application identity: `core.SpinRequestSequence` in **Spin**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: None
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/spin_credit.py`
- Used by: `core/services/spin_credit.py`

### `core_stafflifecyclechangeplan`

- Application identity: `core.StaffLifecycleChangePlan` in **Access**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`
- Children: `core.StaffTelegramOnboarding`
- Cross-domain parents: None
- Direct ORM writers: `core/services/staff_lifecycle.py`, `core/services/user_hard_delete.py`
- Used by: `core/services/staff_lifecycle.py`, `core/services/staff_telegram_onboarding.py`, `core/services/user_hard_delete.py`

### `core_stafftelegramgroupinvitation`

- Application identity: `core.StaffTelegramGroupInvitation` in **Access**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.GroupSheetConfiguration`, `core.StaffTelegramOnboarding`
- Children: None
- Cross-domain parents: `core.GroupSheetConfiguration`
- Direct ORM writers: `core/services/staff_telegram_onboarding.py`
- Used by: `core/services/staff_lifecycle.py`, `core/services/staff_telegram_onboarding.py`

### `core_stafftelegramonboarding`

- Application identity: `core.StaffTelegramOnboarding` in **Access**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.StaffLifecycleChangePlan`
- Children: `core.StaffTelegramGroupInvitation`
- Cross-domain parents: None
- Direct ORM writers: `core/services/staff_telegram_onboarding.py`
- Used by: `core/management/commands/audit_staff_launcher_readiness.py`, `core/services/staff_lifecycle.py`, `core/services/staff_telegram_onboarding.py`, `core/services/user_hard_delete.py`

### `core_tatactiontask`

- Application identity: `core.TatActionTask` in **Tat**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.GroupSheetConfiguration`, `core.TatActionTask`, `core.TatResponsibilityAssignment`, `core.TatTrackerCase`
- Children: `core.TatActionTask`, `core.TatActionTaskLocator`, `core.TatActionTaskRecipient`, `core.TatTaskRerouteEvent`
- Cross-domain parents: `core.GroupSheetConfiguration`
- Direct ORM writers: `core/services/tat_notifications.py`
- Used by: `core/services/staff_lifecycle.py`, `core/services/tat_full_reset.py`, `core/services/tat_notifications.py`, `core/services/tat_register.py`, `core/services/user_hard_delete.py`

### `core_tatactiontasklocator`

- Application identity: `core.TatActionTaskLocator` in **Tat**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.TatActionTask`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/tat_notifications.py`
- Used by: `core/services/tat_full_reset.py`, `core/services/tat_notifications.py`, `core/services/user_hard_delete.py`

### `core_tatactiontaskrecipient`

- Application identity: `core.TatActionTaskRecipient` in **Tat**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.TatActionTask`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/tat_notifications.py`
- Used by: `core/services/tat_full_reset.py`, `core/services/tat_notifications.py`, `core/services/tat_register.py`, `core/services/user_hard_delete.py`

### `core_tatcasesequence`

- Application identity: `core.TatCaseSequence` in **Tat**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: None
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/tat_tracker.py`
- Used by: `core/services/tat_full_reset.py`, `core/services/tat_tracker.py`

### `core_tatconfigurationevent`

- Application identity: `core.TatConfigurationEvent` in **Tat**
- Source of truth: **Yes**
- Retention: Retained with the permanent workflow or compliance audit record.
- Parents: `auth.User`, `core.GroupSheetConfiguration`
- Children: None
- Cross-domain parents: `core.GroupSheetConfiguration`
- Direct ORM writers: `core/services/tat_configuration.py`, `core/services/tat_presentation.py`, `core/services/tat_setup.py`
- Used by: `core/services/tat_configuration.py`, `core/services/tat_full_reset.py`, `core/services/tat_presentation.py`, `core/services/tat_setup.py`

### `core_tatescalationrule`

- Application identity: `core.TatEscalationRule` in **Tat**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.GroupSheetConfiguration`
- Children: None
- Cross-domain parents: `core.GroupSheetConfiguration`
- Direct ORM writers: `core/services/miniapp_settings.py`
- Used by: `core/services/miniapp_settings.py`, `core/services/tat_full_reset.py`, `core/services/workflow_sla.py`

### `core_tatgroupexceptionstatus`

- Application identity: `core.TatGroupExceptionStatus` in **Tat**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.GroupSheetConfiguration`
- Children: None
- Cross-domain parents: `core.GroupSheetConfiguration`
- Direct ORM writers: `core/services/tat_notifications.py`
- Used by: `core/services/tat_full_reset.py`, `core/services/tat_notifications.py`

### `core_tatnotificationprocessorrun`

- Application identity: `core.TatNotificationProcessorRun` in **Tat**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: None
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/tat_notifications.py`
- Used by: `core/services/tat_full_reset.py`, `core/services/tat_notifications.py`, `core/services/tat_production.py`

### `core_tatpresentationsettings`

- Application identity: `core.TatPresentationSettings` in **Tat**
- Source of truth: **Yes**
- Retention: Retain while referenced; retire or deactivate instead of deleting governed history.
- Parents: `auth.User`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/fresh_database_baseline.py`
- Used by: `core/services/fresh_database_baseline.py`, `core/services/tat_full_reset.py`, `core/services/tat_presentation.py`

### `core_tatprivatealertconnection`

- Application identity: `core.TatPrivateAlertConnection` in **Tat**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`
- Children: `core.TatPrivateAlertConnectionEvent`
- Cross-domain parents: None
- Direct ORM writers: `core/services/tat_notifications.py`
- Used by: `core/services/tat_full_reset.py`, `core/services/tat_notifications.py`, `core/services/tat_production.py`, `core/services/tat_responsibilities.py`, `core/services/user_hard_delete.py`

### `core_tatprivatealertconnectionevent`

- Application identity: `core.TatPrivateAlertConnectionEvent` in **Tat**
- Source of truth: **Yes**
- Retention: Retained with the permanent workflow or compliance audit record.
- Parents: `core.TatPrivateAlertConnection`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/tat_notifications.py`
- Used by: `core/services/tat_full_reset.py`, `core/services/tat_notifications.py`

### `core_tatrepairjob`

- Application identity: `core.TatRepairJob` in **Tat**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.GroupSheetConfiguration`, `core.Product`
- Children: None
- Cross-domain parents: `core.GroupSheetConfiguration`, `core.Product`
- Direct ORM writers: `core/services/tat_repair_jobs.py`
- Used by: `core/services/durable_jobs.py`, `core/services/product_catalog.py`, `core/services/product_deletion.py`, `core/services/tat_full_reset.py`, `core/services/tat_repair_jobs.py`

### `core_tatresponsibilityassignment`

- Application identity: `core.TatResponsibilityAssignment` in **Tat**
- Source of truth: **Yes**
- Retention: Retain while referenced; retire or deactivate instead of deleting governed history.
- Parents: `auth.User`, `core.GroupSheetConfiguration`
- Children: `core.TatActionTask`, `core.TatResponsibilityBackup`, `core.TatResponsibilityChangePlan`, `core.TatResponsibilityEvent`
- Cross-domain parents: `core.GroupSheetConfiguration`
- Direct ORM writers: `core/services/tat_responsibilities.py`, `core/services/user_hard_delete.py`
- Used by: `core/services/staff_lifecycle.py`, `core/services/tat_full_reset.py`, `core/services/tat_notifications.py`, `core/services/tat_production.py`, `core/services/tat_reporting.py`, `core/services/tat_responsibilities.py`, `core/services/tat_setup.py`, `core/services/user_hard_delete.py`

### `core_tatresponsibilitybackup`

- Application identity: `core.TatResponsibilityBackup` in **Tat**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.TatResponsibilityAssignment`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/staff_lifecycle.py`, `core/services/user_hard_delete.py`
- Used by: `core/services/staff_lifecycle.py`, `core/services/tat_full_reset.py`, `core/services/user_hard_delete.py`

### `core_tatresponsibilitychangeplan`

- Application identity: `core.TatResponsibilityChangePlan` in **Tat**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.TatResponsibilityAssignment`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/tat_responsibilities.py`
- Used by: `core/services/tat_full_reset.py`, `core/services/tat_responsibilities.py`

### `core_tatresponsibilityevent`

- Application identity: `core.TatResponsibilityEvent` in **Tat**
- Source of truth: **Yes**
- Retention: Retained with the permanent workflow or compliance audit record.
- Parents: `auth.User`, `core.TatResponsibilityAssignment`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/tat_responsibilities.py`, `core/services/user_hard_delete.py`
- Used by: `core/services/tat_full_reset.py`, `core/services/tat_responsibilities.py`, `core/services/user_hard_delete.py`

### `core_tattaskrerouteevent`

- Application identity: `core.TatTaskRerouteEvent` in **Tat**
- Source of truth: **Yes**
- Retention: Retained with the permanent workflow or compliance audit record.
- Parents: `auth.User`, `core.TatActionTask`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/tat_notifications.py`
- Used by: `core/services/tat_full_reset.py`, `core/services/tat_notifications.py`

### `core_tattrackerapprovalcertificate`

- Application identity: `core.TatTrackerApprovalCertificate` in **Tat**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.TatTrackerCase`, `core.TatTrackerEvent`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/tat_tracker.py`, `core/services/tat_update_dispatch.py`, `core/services/workflow_pilot_purge.py`
- Used by: `core/api/views.py`, `core/services/tat_full_reset.py`, `core/services/tat_signature.py`, `core/services/tat_tracker.py`, `core/services/tat_update_dispatch.py`, `core/services/workflow_pilot_purge.py`

### `core_tattrackercase`

- Application identity: `core.TatTrackerCase` in **Tat**
- Source of truth: **Yes**
- Retention: Retained with the permanent TAT operational record.
- Parents: `core.Product`, `core.ProductVersion`
- Children: `core.TatActionTask`, `core.TatTrackerApprovalCertificate`, `core.TatTrackerEvent`, `core.TatUpdateSideEffectDispatch`, `core.WorkflowTatMetricRebuildRequest`
- Cross-domain parents: `core.Product`, `core.ProductVersion`
- Direct ORM writers: `core/services/group_reset.py`, `core/services/tat_tracker.py`, `core/services/workflow_pilot_purge.py`
- Used by: `core/api/views.py`, `core/services/database_catalog.py`, `core/services/fresh_database_baseline.py`, `core/services/group_reset.py`, `core/services/product_catalog.py`, `core/services/product_deletion.py`, `core/services/reporting_relationships.py`, `core/services/sheet_publication.py`, `core/services/sync_governance.py`, `core/services/tat_configuration.py`, `core/services/tat_full_reset.py`, `core/services/tat_notifications.py`, `core/services/tat_production.py`, `core/services/tat_register.py`, `core/services/tat_repair_jobs.py`, `core/services/tat_reporting.py`, `core/services/tat_setup.py`, `core/services/tat_tracker.py`, `core/services/tat_update_dispatch.py`, `core/services/workflow_data_mode.py`, `core/services/workflow_pilot_purge.py`, `core/services/workflow_sla.py`, `core/services/workflow_timeline.py`

### `core_tattrackerevent`

- Application identity: `core.TatTrackerEvent` in **Tat**
- Source of truth: **Yes**
- Retention: Retained with the permanent workflow or compliance audit record.
- Parents: `auth.User`, `core.TatTrackerCase`
- Children: `core.TatTrackerApprovalCertificate`
- Cross-domain parents: None
- Direct ORM writers: `core/services/tat_tracker.py`
- Used by: `core/services/group_reset.py`, `core/services/tat_full_reset.py`, `core/services/tat_tracker.py`

### `core_tatupdatesideeffectdispatch`

- Application identity: `core.TatUpdateSideEffectDispatch` in **Tat**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.TatTrackerCase`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/tat_update_dispatch.py`
- Used by: `core/api/views.py`, `core/services/tat_full_reset.py`, `core/services/tat_notifications.py`, `core/services/tat_production.py`, `core/services/tat_update_dispatch.py`

### `core_telegramstaffactivation`

- Application identity: `core.TelegramStaffActivation` in **Platform**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/staff_lifecycle.py`
- Used by: `core/services/staff_lifecycle.py`, `core/services/user_hard_delete.py`

### `core_userharddeletionbatch`

- Application identity: `core.UserHardDeletionBatch` in **Platform**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`
- Children: `core.DeletedUserIdentity`
- Cross-domain parents: None
- Direct ORM writers: `core/services/user_hard_delete.py`
- Used by: `core/services/user_hard_delete.py`

### `core_userminiapppreference`

- Application identity: `core.UserMiniAppPreference` in **Platform**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/miniapp_settings.py`
- Used by: `core/services/miniapp_settings.py`, `core/services/user_hard_delete.py`

### `core_userprofile`

- Application identity: `core.UserProfile` in **Access**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/staff_lifecycle.py`, `core/services/staff_telegram_onboarding.py`
- Used by: `core/services/access_control.py`, `core/services/database_catalog.py`, `core/services/staff_lifecycle.py`, `core/services/staff_telegram_onboarding.py`, `core/services/telegram_identity.py`, `core/services/user_hard_delete.py`

### `core_workflowconfigurationchangerequest`

- Application identity: `core.WorkflowConfigurationChangeRequest` in **Platform**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.GroupSheetConfiguration`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/miniapp_settings.py`, `core/services/user_hard_delete.py`
- Used by: `core/api/views.py`, `core/services/miniapp_settings.py`, `core/services/tat_full_reset.py`, `core/services/tat_presentation.py`, `core/services/user_hard_delete.py`

### `core_workflowdatamodeevent`

- Application identity: `core.WorkflowDataModeEvent` in **Platform**
- Source of truth: **Yes**
- Retention: Retained with the permanent workflow or compliance audit record.
- Parents: `auth.User`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/workflow_data_mode.py`, `core/services/workflow_pilot_purge.py`
- Used by: `core/services/tat_full_reset.py`, `core/services/workflow_data_mode.py`, `core/services/workflow_pilot_purge.py`

### `core_workflowdatamodestate`

- Application identity: `core.WorkflowDataModeState` in **Platform**
- Source of truth: **Yes**
- Retention: Retain while referenced; retire or deactivate instead of deleting governed history.
- Parents: `auth.User`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/tat_full_reset.py`, `core/services/workflow_data_mode.py`
- Used by: `core/services/tat_full_reset.py`, `core/services/tat_production.py`, `core/services/workflow_data_mode.py`, `core/services/workflow_pilot_purge.py`

### `core_workflowpilotformulareadiness`

- Application identity: `core.WorkflowPilotFormulaReadiness` in **Platform**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`, `core.GroupSheetConfiguration`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/workflow_pilot_purge.py`
- Used by: `core/services/tat_full_reset.py`, `core/services/workflow_pilot_purge.py`

### `core_workflowpilotpurgerun`

- Application identity: `core.WorkflowPilotPurgeRun` in **Platform**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/workflow_pilot_purge.py`
- Used by: `core/services/tat_full_reset.py`, `core/services/workflow_pilot_purge.py`

### `core_workflowrolecapability`

- Application identity: `core.WorkflowRoleCapability` in **Access**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: None
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/access_control.py`
- Used by: `core/services/access_control.py`, `core/services/access_control_reporting.py`, `core/services/fresh_database_baseline.py`, `core/services/origination_access.py`, `core/services/staff_lifecycle.py`, `core/services/workflow_access.py`, `core/services/workflow_capabilities.py`

### `core_workflowrolecapabilityauditevent`

- Application identity: `core.WorkflowRoleCapabilityAuditEvent` in **Access**
- Source of truth: **Yes**
- Retention: Retained with the permanent workflow or compliance audit record.
- Parents: `auth.User`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/access_control.py`
- Used by: `core/services/access_control.py`

### `core_workflowslaescalation`

- Application identity: `core.WorkflowSlaEscalation` in **Platform**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/workflow_pilot_purge.py`, `core/services/workflow_sla.py`
- Used by: `core/services/portal_dashboard.py`, `core/services/tat_full_reset.py`, `core/services/workflow_escalations.py`, `core/services/workflow_pilot_purge.py`, `core/services/workflow_sla.py`

### `core_workflowtatdailymetric`

- Application identity: `core.WorkflowTatDailyMetric` in **Tat**
- Source of truth: **No**
- Retention: Retained according to the reporting or telemetry aggregation policy.
- Parents: `core.Product`
- Children: None
- Cross-domain parents: `core.Product`
- Direct ORM writers: `core/services/tat_reporting.py`, `core/services/workflow_pilot_purge.py`, `core/services/workflow_sla.py`
- Used by: `core/services/product_catalog.py`, `core/services/product_deletion.py`, `core/services/tat_full_reset.py`, `core/services/tat_reporting.py`, `core/services/workflow_pilot_purge.py`, `core/services/workflow_sla.py`

### `core_workflowtatmetricrebuildrequest`

- Application identity: `core.WorkflowTatMetricRebuildRequest` in **Tat**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `core.TatTrackerCase`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: `core/services/tat_presentation.py`, `core/services/tat_reporting.py`
- Used by: `core/services/tat_full_reset.py`, `core/services/tat_presentation.py`, `core/services/tat_reporting.py`

### `core_workflowtimelineannotation`

- Application identity: `core.WorkflowTimelineAnnotation` in **Platform**
- Source of truth: **Yes**
- Retention: Retained with the owning business record according to its workflow policy.
- Parents: `auth.User`
- Children: None
- Cross-domain parents: None
- Direct ORM writers: No direct manager mutation found; inspect owning service
- Used by: `core/services/tat_full_reset.py`, `core/services/workflow_timeline.py`
