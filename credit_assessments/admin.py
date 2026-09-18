from django.contrib import admin

from .models import (
    AnalysisPackage,
    AnalysisQuestion,
    AssessmentDecision,
    AssessmentDocument,
    AssessmentEvent,
    AssessmentSecret,
    CreditAssessment,
    EngineJob,
    MailboxCursor,
    QuestionResponse,
    QuestionValidationEvent,
    StatementMailReceipt,
)

# The repository's conservative admin fallback registers every otherwise
# unregistered model. Replace those generated registrations with bounded views,
# especially so encrypted passcode ciphertext is never rendered.
for _model in (
    CreditAssessment, StatementMailReceipt, MailboxCursor, AssessmentDocument,
    AssessmentSecret, AnalysisPackage, AnalysisQuestion, QuestionResponse,
    QuestionValidationEvent, AssessmentDecision, AssessmentEvent, EngineJob,
):
    if admin.site.is_registered(_model):
        admin.site.unregister(_model)


@admin.register(CreditAssessment)
class CreditAssessmentAdmin(admin.ModelAdmin):
    list_display = ('tat_case', 'state', 'revision', 'updated_at')
    list_filter = ('state',)
    search_fields = ('tat_case__case_id', 'tat_case__client_name')
    readonly_fields = ('id', 'revision', 'created_at', 'updated_at')


@admin.register(StatementMailReceipt)
class StatementMailReceiptAdmin(admin.ModelAdmin):
    list_display = ('attachment_name', 'forwarding_sender', 'status', 'statement_full_year', 'inbox_received_at')
    list_filter = ('status', 'statement_full_year')
    search_fields = ('attachment_name', 'forwarding_sender', 'gmail_message_id')
    readonly_fields = [field.name for field in StatementMailReceipt._meta.fields]


@admin.register(AssessmentSecret)
class AssessmentSecretAdmin(admin.ModelAdmin):
    fields = ('assessment', 'key_version', 'reveal_count', 'last_revealed_at', 'destroyed_at', 'updated_at')
    readonly_fields = fields
    list_display = ('assessment', 'key_version', 'reveal_count', 'destroyed_at')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


for model in (
    MailboxCursor, AssessmentDocument, AnalysisPackage,
    AnalysisQuestion, QuestionResponse, QuestionValidationEvent,
    AssessmentDecision, AssessmentEvent, EngineJob,
):
    admin.site.register(model)
