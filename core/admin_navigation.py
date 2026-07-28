"""Curated navigation for the Django Admin operations console.

Unfold falls back to Django's complete app/model registry when no sidebar is
configured.  That is useful for a generic admin, but this project has enough
workflow and audit models that the fallback becomes an unusable flat list.
The navigation below is deliberately task-oriented while every model remains
available through the global search command.
"""

from __future__ import annotations

from collections.abc import Callable

from django.apps import apps
from django.contrib import admin
from django.urls import NoReverseMatch, reverse


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


def _superuser(request) -> bool:
    return bool(getattr(request, "user", None) and request.user.is_superuser)


def get_admin_navigation(request) -> list[dict]:
    """Return the small, workflow-oriented sidebar shown in Django Admin."""

    operations = [
        {"title": "Dashboard", "link": reverse("admin:index"), "icon": "dashboard"},
        _model_item("core.JawabuFarmerMaster", "Jawabu farmer master data", "groups"),
        _model_item("core.JawabuCustomer", "Jawabu customers", "person_search"),
        _model_item("core.JawabuVisitRecord", "Jawabu visits", "location_on"),
        _model_item("core.JawabuDataQualityIssue", "Data quality issues", "rule"),
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
        _model_item("auth.User", "Users", "group"),
        _model_item("auth.Group", "Groups", "groups"),
        _model_item("core.OperationalLocation", "Branches and counties", "map"),
        _model_item("core.GroupSheetConfiguration", "Workflow groups", "hub"),
        _model_item("core.RequisitionTemplate", "Requisition templates", "description"),
        _model_item("core.PaymentDocumentTemplate", "Payment templates", "article"),
        _custom_item("Add staff user", "admin:auth_user_add_staff", "person_add", _superuser),
    ]
    technical = [
        _model_item("core.RawMessage", "Raw messages", "mark_chat_unread"),
        _model_item("core.ProcessedMessage", "Processed messages", "task_alt"),
        _model_item("core.ComplaintCaseEvidence", "Complaint evidence", "folder_shared"),
        _model_item("core.MediaAttachment", "Media attachments", "perm_media"),
        _model_item("core.LiveSheetRecordChange", "Live sheet changes", "sync_problem"),
        _model_item("core.FcaImportRecord", "FCA import records", "input"),
        _model_item("core.JawabuPipelineEvent", "Pipeline events", "event_note"),
        _model_item("core.TatTrackerApprovalCertificate", "Approval certificates", "verified"),
    ]

    groups = [
        {"title": "Operations", "items": [item for item in operations if item]},
        {
            "title": "Reviews and workflows",
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
