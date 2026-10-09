"""Reviewed deletion ownership, not a generic permission to erase every model.

Configuration can be retired while its historical consumers survive. Evidence
selected by itself is promoted to its owning workspace, never amputated from a
signed packet. Independent identities, access policy and final standings are
intentionally absent. New relationships fail closed until reviewed.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Policy:
    kind: str
    owner: str = ''
    retire: tuple = ()


def config(**values):
    return Policy('configuration', retire=tuple(values.items()))


def evidence(owner):
    return Policy('evidence', owner)


REGISTRY = {
    'core.Product': config(active=False),
    'core.ProductVersion': config(status='retired'),
    'core.ProductAlias': evidence('product'),
    'core.ProductFee': evidence('product_version'),
    'core.ProductRequirement': evidence('product_version'),
    'core.ProductCustomAttribute': evidence('product_version'),
    'core.ProductTatConfiguration': evidence('product_version'),
    'core.ProductVersionEvent': evidence('product_version'),
    'core.ProductAvailability': config(active=False),
    'core.ProductMappingIssue': Policy('operational'),
    'core.ComplaintCategory': config(active=False),
    'core.ComplaintCategoryAlias': evidence('category'),
    'core.ComplaintCategoryAvailability': config(active=False),
    'core.ParsedMessage': Policy('operational'),
    'core.CaseUpdate': evidence('parsed_message'),
    'core.ComplaintCaseControl': evidence('parsed_message'),
    'core.ComplaintCaseEvidence': evidence('parsed_message'),
    'core.ComplaintCaseEvent': evidence('case'),
    'core.ComplaintCaseImportBatch': Policy('operational'),
    'core.ComplaintCaseImportItem': evidence('parsed_message'),
    'core.SpinCreditRequest': Policy('operational'),
    'core.SpinBatchReviewItem': Policy('operational'),
    'core.TatTrackerCase': Policy('operational'),
    'core.TatTrackerEvent': evidence('case'),
    'core.TatTrackerApprovalCertificate': evidence('case'),
    'core.TatActionTask': evidence('case'),
    'core.TatActionTaskLocator': evidence('task'),
    'core.TatActionTaskRecipient': evidence('task'),
    'core.TatTaskRerouteEvent': evidence('task'),
    'core.TatUpdateSideEffectDispatch': evidence('case'),
    'core.WorkflowTatMetricRebuildRequest': evidence('case'),
    'core.WorkflowTatDailyMetric': Policy('projection'),
    'core.WorkflowTimelineAnnotation': Policy('projection'),
    'core.WorkflowSlaEscalation': Policy('projection'),
    'core.TatRepairJob': Policy('operational'),
    'core.TatResponsibilityAssignment': config(active=False),
    'core.TatResponsibilityBackup': evidence('assignment'),
    'core.TatResponsibilityChangePlan': evidence('assignment'),
    'core.TatEscalationRule': config(active=False),
    'core.TatPresentationSettings': Policy('configuration'),
    'core.JawabuFarmerMaster': Policy('operational'),
    'core.JawabuVisitRecord': Policy('operational'),
    'core.JawabuApprovalRecord': evidence('farmer'),
    'core.JawabuApprovalCondition': evidence('approval'),
    'core.JawabuPipelineEvent': evidence('farmer'),
    'core.JawabuCaseComment': evidence('farmer'),
    'core.JawabuDataQualityIssue': evidence('farmer'),
    'core.JawabuDataQualityResolution': evidence('issue'),
    'core.JawabuCustomerFieldProvenance': evidence('farmer'),
    'core.PortalCaseWorkspace': evidence('farmer'),
    'core.JawabuFarmerUploadBatch': Policy('operational'),
    'core.FcaImportRecord': Policy('operational'),
    'core.RequisitionBatch': Policy('operational'),
    'core.RequisitionTemplate': config(is_active=False),
    'core.PaymentDocumentTemplate': config(is_active=False),
    'core.InvoiceUploadBatch': Policy('operational'),
    'core.ParsedInvoice': Policy('operational'),
    'core.ParsedInvoiceEvent': evidence('invoice'),
    'core.InvoiceIdentityReview': evidence('invoice'),
    'core.JawabuHouseholdRelationship': evidence('farmer'),
    'core.InvoiceNameChangeBatch': Policy('operational'),
    'core.InvoiceNameChangeItem': evidence('batch'),
    'core.InvoiceNameChangeLetterArtifact': evidence('batch'),
    'core.InvoiceNameChangeLetterTemplate': config(is_active=False),
    'core.PaymentDocument': Policy('operational'),
    'core.DocumentPhysicalSignoff': Policy('evidence'),
    'core.DocumentPhysicalSignoffEvent': evidence('signoff'),
    'core.DocumentSignoffPolicy': config(is_active=False),
    'core.PortalReportDefinition': config(is_active=False),
    'core.PortalReportChart': evidence('definition'),
    'origination.OriginationDataField': config(active=False),
    'origination.OriginationDataFieldEvent': evidence('data_field'),
    'origination.OriginationProductDefinition': config(is_active=False, lifecycle_status='retired'),
    'origination.OriginationProductDefinitionEvent': evidence('product_definition'),
    'origination.OriginationFieldReviewIssue': evidence('product_definition'),
    'origination.OriginationDocumentTemplate': config(status='retired'),
    'origination.OriginationDocumentProductEligibility': Policy('configuration'),
    'origination.OriginationProductDocumentAssignment': Policy('configuration'),
    'origination.OriginationDocumentTemplateEvent': evidence('template'),
    'origination.OriginationTemplateConfigurationRevision': evidence('template'),
    'origination.OriginationConsentPolicyVersion': config(status='retired'),
    'origination.OriginationStampAsset': config(active=False),
    'origination.LoanOriginationApplication': Policy('operational'),
    'origination.OriginationApplicationEvent': evidence('application'),
    'origination.OriginationCommercialException': evidence('application'),
    'origination.OriginationReportingValue': evidence('application'),
    'origination.OriginationReviewerNotice': evidence('application'),
    'origination.OriginationCorrectionRequest': evidence('application'),
    'origination.OriginationCorrectionItem': evidence('correction_request'),
    'origination.OriginationRequirementEvidence': evidence('application'),
    'origination.OriginationApplicationDocument': evidence('application'),
    'origination.OriginationSigningPackage': evidence('application'),
    'origination.OriginationSignerSession': evidence('package'),
    'origination.OriginationOtpChallenge': evidence('session'),
    'origination.OriginationSigningRequestEvent': evidence('session'),
    'origination.OriginationSigningAction': evidence('package'),
    'origination.OriginationSigningActionInvalidation': evidence('action'),
    'requisitions.OrderWorkbookVersion': evidence('batch'),
    'requisitions.OrderWorkspaceEvent': evidence('batch'),
    'payments.PaymentBatch': Policy('operational'),
    'payments.PaymentBatchCase': evidence('batch'),
    'payments.PaymentCaseReview': evidence('membership'),
    'payments.PaymentBatchEvent': evidence('batch'),
    'payments.PaymentReceiptBatch': Policy('operational'),
    'payments.PaymentReceiptItem': evidence('receipt_batch'),
    'payments.InvoiceNameAgreement': evidence('artifact'),
    'hb_operations.HomeBiogasAction': evidence('farmer'),
    'hb_operations.HomeBiogasActionEvent': evidence('action'),
    'credit_assessments.CreditAssessment': evidence('tat_case'),
    'credit_assessments.StatementMailReceipt': Policy('operational'),
    'credit_assessments.AssessmentDocument': evidence('assessment'),
    'credit_assessments.AssessmentSecret': evidence('assessment'),
    'credit_assessments.AnalysisPackage': evidence('assessment'),
    'credit_assessments.AnalysisQuestion': evidence('package'),
    'credit_assessments.QuestionResponse': evidence('question'),
    'credit_assessments.QuestionValidationEvent': evidence('response'),
    'credit_assessments.AssessmentDecision': evidence('assessment'),
    'credit_assessments.AssessmentEvent': evidence('assessment'),
    'credit_assessments.EngineJob': evidence('assessment'),
    'core.PortalVoiceTranscriptionAttempt': Policy('projection'),
}

# These references survive, and their FK is nullable. Access grants are NOT
# unlinked: nulling product_ref would silently broaden their scope.
UNLINK = {
    'core.MediaAttachment.jawabu_farmer', 'core.MediaAttachment.order_update',
    'core.JawabuMediaAccessEvent.farmer', 'core.JawabuMediaAccessEvent.attachment',
    'core.TatResponsibilityEvent.assignment',
    'payments.PaymentSequenceEvent.batch',
    'core.JawabuFarmerMaster.requisition_batch',
    'origination.OriginationDocumentTemplate.product_definition',
}

# Raw input, shared people, numbering and finalized recognition facts survive.
# Foreign references in this list keep the target definition for history.
RETAIN_REFERENCERS = {
    'core.AccessGrant', 'core.EmergencyAccessGrant', 'core.JawabuApprovalDelegation',
    'core.JawabuMediaAccessEvent', 'core.MediaAttachment',
    'requisitions.OrderNumberClaim', 'payments.PaymentNumberClaim',
    'payments.PaymentSequenceEvent',
}
