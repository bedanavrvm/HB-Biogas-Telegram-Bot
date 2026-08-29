"""Curated navigation for the Django Admin operations console.

Unfold falls back to Django's complete app/model registry when no sidebar is
configured.  That is useful for a generic admin, but this project has enough
workflow and audit models that the fallback becomes an unusable flat list.
The navigation below is deliberately task-oriented while every model remains
available through the global search command.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlencode

from django.apps import apps
from django.conf import settings
from django.contrib import admin
from django.db import DatabaseError
from django.urls import NoReverseMatch, reverse

from core.models import GroupSheetConfiguration, StaffLifecycleChangePlan


WORKFLOW_GROUP_LABELS = {
    "case": "Complaint cases",
    "order_approval": "Order approvals",
    "jawabu_homebiogas": "Jawabu HomeBiogas",
    "spin_credit_analysis": "SPIN / Credit",
    "tat_tracker": "TAT Tracker",
}


def _model_permission(label: str) -> Callable:
    """Build a permission callback for one model navigation item."""

    def allowed(request) -> bool:
        if not getattr(request, "user", None) or not request.user.is_authenticated:
            return False
        try:
            model = apps.get_model(label)
        except LookupError:
            return False
        model_admin = admin.site._registry.get(model)
        if model_admin is None:
            return False
        return bool(
            model_admin.has_module_permission(request)
            and (
                model_admin.has_view_permission(request)
                or model_admin.has_change_permission(request)
                or model_admin.has_add_permission(request)
            )
        )

    return allowed


def _model_item(label: str, title: str, icon: str) -> dict:
    try:
        model = apps.get_model(label)
        link = reverse(
            f"admin:{model._meta.app_label}_{model._meta.model_name}_changelist"
        )
    except (LookupError, NoReverseMatch):
        # A missing optional model or URL should not make the entire Admin
        # sidebar fail to render during a rolling deployment.
        return {}
    return {
        "title": title,
        "link": link,
        "icon": icon,
        "permission": _model_permission(label),
    }


def _custom_item(title: str, link_name: str, icon: str, permission: Callable) -> dict:
    return {
        "title": title,
        "link": reverse(link_name),
        "icon": icon,
        "permission": permission,
    }


def _link_item(title: str, link: str, icon: str, permission: Callable) -> dict:
    """Create a sidebar item for an object-specific admin route."""
    return {
        "title": title,
        "link": link,
        "icon": icon,
        "permission": permission,
    }


def _filtered_model_item(label: str, title: str, icon: str, **filters) -> dict:
    """Link to a normal admin list narrowed to one workflow group."""
    item = _model_item(label, title, icon)
    if not item:
        return item
    query = {
        f"{field}__exact": value
        for field, value in filters.items()
        if value not in (None, "")
    }
    if query:
        item["link"] = f"{item['link']}?{urlencode(query)}"
    return item


def _group_configuration_permission(config: GroupSheetConfiguration) -> Callable:
    """Keep object-specific shortcuts behind the configuration's own access check."""

    def allowed(request) -> bool:
        if not getattr(request, "user", None) or not request.user.is_authenticated:
            return False
        model_admin = admin.site._registry.get(GroupSheetConfiguration)
        if model_admin is None:
            return False
        return bool(
            model_admin.has_view_permission(request, config)
            or model_admin.has_change_permission(request, config)
        )

    return allowed


def _group_workflow_items(config: GroupSheetConfiguration) -> list[dict]:
    """Keep the operational register and maintenance tools beside its group."""
    if not config.pk:
        return []

    permission = _group_configuration_permission(config)
    group_id = config.group_id
    workflow_type = str((config.workflow or {}).get("type") or "").strip()
    items = [
        _link_item(
            "Configuration",
            reverse("admin:core_groupsheetconfiguration_change", args=[config.pk]),
            "settings",
            permission,
        ),
        _link_item(
            "Live Sheet (view only)",
            reverse("admin:core_groupsheetconfiguration_live_records", args=[config.pk]),
            "table_view",
            permission,
        ),
    ]

    if workflow_type == "tat_tracker":
        items.extend([
            _filtered_model_item("core.TatTrackerCase", "Cases", "schedule", group_id=group_id),
            _filtered_model_item("core.TatTrackerEvent", "Event history", "timeline", group_id=group_id),
            _filtered_model_item(
                "core.TatResponsibilityAssignment", "Access & responsibilities", "account_tree",
                group_configuration_id=config.pk,
            ),
            _filtered_model_item(
                "core.TatActionTask", "Private task inbox", "inbox",
                group_configuration_id=config.pk,
            ),
            _link_item(
                "Reconcile TAT Sheet",
                reverse("admin:core_groupsheetconfiguration_tat_repair", args=[config.pk]),
                "build_circle",
                _superuser,
            ),
            _link_item(
                "Find duplicate rows",
                reverse("admin:core_groupsheetconfiguration_tat_duplicates", args=[config.pk]),
                "content_copy",
                _superuser,
            ),
        ])
    elif workflow_type == "spin_credit_analysis":
        items.append(
            _filtered_model_item("core.SpinCreditRequest", "SPIN / CRB requests", "fact_check", group_id=group_id)
        )
    elif workflow_type == "order_approval":
        items.extend([
            _filtered_model_item("core.OrderApprovalUpdate", "Order updates", "approval", group_id=group_id),
            _filtered_model_item("core.MediaAttachment", "Media uploads", "perm_media", group_id=group_id),
        ])
    elif workflow_type == "jawabu_homebiogas":
        items.extend([
            _filtered_model_item("core.JawabuVisitRecord", "JBL visit imports", "location_on", group_id=group_id),
            _filtered_model_item("core.JawabuFarmerUploadBatch", "Farmer uploads", "cloud_upload", group_id=group_id),
        ])
    else:
        # Complaint handling is also the safe fallback for legacy/manual group
        # configurations that do not yet carry a workflow type.
        items.extend([
            _filtered_model_item("core.ParsedMessage", "Cases", "support_agent", group_id=group_id),
            _filtered_model_item("core.CaseUpdate", "Case updates", "history", group_id=group_id),
        ])
    return [item for item in items if item]


def _configured_workflow_groups() -> list[dict]:
    """Generate one collapsible sidebar section per enabled configuration."""
    groups = []
    configurations = GroupSheetConfiguration.objects.filter(enabled=True).order_by(
        "display_name", "group_id"
    )
    for config in configurations:
        workflow_type = str((config.workflow or {}).get("type") or "").strip()
        workflow_label = WORKFLOW_GROUP_LABELS.get(workflow_type, "Workflow group")
        name = config.display_name or config.group_id
        groups.append({
            "title": f"{workflow_label}: {name}",
            "collapsible": True,
            "items": _group_workflow_items(config),
        })
    return groups


def _superuser(request) -> bool:
    return bool(getattr(request, "user", None) and request.user.is_superuser)


def _staff_approver(request) -> bool:
    from core.services.access_control import can_approve_access_change

    return bool(getattr(request, 'user', None) and can_approve_access_change(request.user))


def _staff_approvals_item(request) -> dict:
    try:
        plans = StaffLifecycleChangePlan.objects.filter(
            status=StaffLifecycleChangePlan.STATUS_PENDING,
            decision_mode=StaffLifecycleChangePlan.DECISION_CHECKER,
        ).only('requested_by_id', 'target_user_id', 'proposed_snapshot')
        if request.user.is_superuser:
            pending = plans.count()
        else:
            plans = plans.exclude(
                requested_by=request.user,
            ).exclude(target_user=request.user)
            pending = sum(
                1 for plan in plans
                if (plan.proposed_snapshot or {}).get('replacement_user_id') != request.user.pk
            )
    except DatabaseError:
        pending = 0
    return _custom_item(
        f'Staff approvals ({pending})',
        'admin:auth_user_staff_approvals',
        'how_to_reg',
        _staff_approver,
    )


def _origination_full_reset_allowed(request) -> bool:
    user = getattr(request, "user", None)
    return bool(
        getattr(settings, 'ORIGINATION_FULL_RESET_ENABLED', False)
        and user
        and user.is_authenticated
        and user.is_active
        and user.is_superuser
    )


def get_admin_navigation(request) -> list[dict]:
    """Return the small, workflow-oriented sidebar shown in Django Admin."""

    operations = [
        {"title": "Dashboard", "link": reverse("admin:index"), "icon": "dashboard"},
        _model_item("core.JawabuFarmerMaster", "Jawabu farmer master data", "groups"),
        _model_item("core.JawabuCustomer", "Jawabu customers", "person_search"),
        _model_item("core.JawabuVisitRecord", "Jawabu visits", "location_on"),
        _model_item("core.JawabuDataQualityIssue", "Data quality issues", "rule"),
        _model_item("core.JawabuCustomerFieldProvenance", "Customer field provenance", "history"),
        _model_item("core.JawabuFarmerUploadBatch", "Farmer upload batches", "cloud_upload"),
        _model_item("core.RequisitionBatch", "Requisition batches", "receipt_long"),
        _model_item("core.InvoiceUploadBatch", "Invoice uploads", "upload_file"),
        _model_item("core.ParsedInvoice", "Parsed invoices", "receipt"),
        _model_item("core.PaymentDocument", "Payment documents", "payments"),
    ]
    reviews = [
        _model_item("core.TatTrackerCase", "TAT tracker cases", "schedule"),
        _model_item("core.TatTrackerEvent", "TAT events", "timeline"),
        _model_item("core.TatRepairJob", "TAT repair jobs", "build_circle"),
        _model_item("core.SpinCreditRequest", "SPIN / CRB requests", "fact_check"),
        _model_item("core.ParsedMessage", "Complaint cases", "support_agent"),
        _model_item("core.OrderApprovalUpdate", "Order approval updates", "approval"),
    ]
    configuration = [
        _staff_approvals_item(request),
        _model_item("auth.User", "Users", "group"),
        _model_item("auth.Group", "Groups", "groups"),
        _model_item("core.WorkflowDataModeState", "SPIN/TAT pilot modes", "science"),
        _model_item("core.TatResponsibilityAssignment", "TAT access & responsibilities", "account_tree"),
        _model_item("core.OperationalLocation", "Global locations", "map"),
        _model_item("core.BranchServiceArea", "Branch service areas", "conversion_path"),
        _model_item("core.OperationalLocationAlias", "Location aliases", "alt_route"),
        _model_item("core.LocationMappingIssue", "Unmapped location values", "rule"),
        _model_item("core.LocationPolicyState", "Location enforcement", "policy"),
        _model_item("core.Product", "Global products", "inventory_2"),
        _model_item("core.ProductVersion", "Product terms and requirements", "price_change"),
        _custom_item(
            "Guided Origination product setup",
            "admin:core_origination_setup_dashboard",
            "route",
            _superuser,
        ),
        _model_item("core.OriginationProductDefinition", "Loan form definitions", "dynamic_form"),
        _model_item("core.OriginationDocumentTemplate", "Origination PDF templates", "picture_as_pdf"),
        _model_item("core.OriginationProductDocumentAssignment", "Product document assignments", "assignment"),
        _model_item("core.OriginationDataField", "Origination data fields", "data_object"),
        _model_item("core.OriginationCommercialException", "Origination commercial exceptions", "gavel"),
        _model_item("core.OriginationStampAsset", "Origination stamp assets", "verified"),
        _model_item("core.OriginationSigningPackage", "Origination signing packages", "draw"),
        _model_item("core.OriginationSignerSession", "Origination signer sessions", "sms"),
        _model_item("core.OriginationOtpChallenge", "Origination OTP delivery", "password"),
        _model_item("core.OriginationFieldReviewIssue", "Legacy fields needing review", "rule"),
        _custom_item(
            "Reset all Origination data",
            "admin:core_origination_full_reset",
            "delete_forever",
            _origination_full_reset_allowed,
        ),
        _model_item("core.ProductMappingIssue", "Unmapped product values", "rule"),
        _model_item("core.ComplaintCategory", "Complaint categories", "category"),
        _model_item("core.ComplaintCategoryAlias", "Complaint category aliases", "alt_route"),
        _model_item("core.ComplaintCategoryAvailability", "Complaint category availability", "lan"),
        _model_item("core.GroupSheetConfiguration", "Workflow groups", "hub"),
        _custom_item("Mini App access matrix", "admin:core_workflowrolecapability_matrix", "admin_panel_settings", _superuser),
        _model_item("core.AccessControlChangeRequest", "Access approval queue", "fact_check"),
        _model_item("core.AccessControlPolicySnapshot", "Policy snapshots", "history"),
        _model_item("core.WorkflowRoleCapabilityAuditEvent", "Access policy audit", "policy",),
        _model_item("core.EmergencyAccessGrant", "Emergency access", "warning"),
        _model_item("core.CapabilityUsageDaily", "Access usage and drift", "analytics"),
        _model_item("core.RequisitionTemplate", "Requisition templates", "description"),
        _model_item("core.PaymentDocumentTemplate", "Payment templates", "article"),
        _model_item("core.InvoiceNameChangeLetterTemplate", "Invoice name change templates", "description"),
        _custom_item("Add staff user", "admin:auth_user_add_staff", "person_add", _superuser),
    ]
    technical = [
        _model_item("core.RawMessage", "Raw messages", "mark_chat_unread"),
        _model_item("core.ProcessedMessage", "Processed messages", "task_alt"),
        _model_item("core.ComplaintCaseEvidence", "Complaint evidence", "folder_shared"),
        _model_item("core.ComplaintCaseControl", "Complaint controls", "assignment_ind"),
        _model_item("core.ComplaintCaseEvent", "Complaint events", "history"),
        _model_item("core.MediaAttachment", "Media attachments", "perm_media"),
        _model_item("core.LiveSheetRecordChange", "Live sheet changes", "sync_problem"),
        _model_item("core.FcaImportRecord", "FCA import records", "input"),
        _model_item("core.JawabuPipelineEvent", "Pipeline events", "event_note"),
        _model_item("core.TatTrackerApprovalCertificate", "Approval certificates", "verified"),
        _model_item("core.TatActionTask", "TAT private tasks", "inbox"),
        _model_item("core.TatPrivateAlertConnection", "TAT private alert connections", "notifications"),
        _model_item("core.TatGroupExceptionStatus", "TAT delivery exceptions", "notification_important"),
        _model_item("core.TatResponsibilityEvent", "TAT responsibility audit", "history"),
        _model_item("core.OriginationDataFieldEvent", "Origination field audit", "history"),
        _model_item("core.LocationConfigurationEvent", "Location configuration audit", "history"),
        _model_item("core.MiniAppDiagnosticSession", "Mini App diagnostic sessions", "monitor_heart"),
        _model_item("core.MiniAppDiagnosticEvent", "Mini App diagnostic events", "timeline"),
        _model_item("core.MiniAppDiagnosticDailyAggregate", "Mini App diagnostic trends", "query_stats"),
    ]

    configured_workflows = _configured_workflow_groups()
    groups = [
        {"title": "Operations", "items": [item for item in operations if item]},
        *configured_workflows,
        {
            "title": "All workflows",
            "collapsible": True,
            "items": [item for item in reviews if item],
        },
        {
            "title": "Configuration",
            "collapsible": True,
            "items": [item for item in configuration if item],
        },
        {
            "title": "Technical records",
            "collapsible": True,
            "items": [item for item in technical if item],
        },
    ]
    return groups
