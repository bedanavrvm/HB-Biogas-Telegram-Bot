"""
URL routing for the core API.
"""
from django.urls import path
from .views import (
    telegram_webhook,
    health_check,
    jawabu_farmers_review,
    jawabu_farmers_review_commit,
    fca_review,
    fca_review_commit,
    order_approval_form,
    order_approval_webapp_lookup,
    order_approval_webapp_suggest,
    order_approval_webapp_submit,
    process_messages,
    resend_unsynced,
    sync_from_sheets,
)
from .portal_views import (
    portal_home,
    portal_dashboard,
    portal_meta,
    portal_jbl_queue,
    portal_log_jbl_visit,
    portal_credit_queue,
    portal_set_credit_decision,
    portal_requisition_queue,
    portal_assign_order,
    portal_requisition_generate,
    portal_requisition_batches,
    portal_all_cases,
    portal_deferred,
    portal_farmer_detail,
)

urlpatterns = [
    path('health/', health_check, name='health_check'),
    path('order-approval/', order_approval_form, name='order_approval_form'),
    path('jawabu-farmers/review/', jawabu_farmers_review, name='jawabu_farmers_review'),
    path('jawabu-farmers/review/commit/', jawabu_farmers_review_commit, name='jawabu_farmers_review_commit'),
    path('fca/review/', fca_review, name='fca_review'),
    path('fca/review/commit/', fca_review_commit, name='fca_review_commit'),
    path('webhook/telegram/', telegram_webhook, name='telegram_webhook'),
    path(
        'order-approval/webapp/submit/',
        order_approval_webapp_submit,
        name='order_approval_webapp_submit',
    ),
    path(
        'order-approval/webapp/lookup/',
        order_approval_webapp_lookup,
        name='order_approval_webapp_lookup',
    ),
    path(
        'order-approval/webapp/suggest/',
        order_approval_webapp_suggest,
        name='order_approval_webapp_suggest',
    ),
    path('process/messages/', process_messages, name='process_messages'),
    path('resync/unsynced/', resend_unsynced, name='resend_unsynced'),
    path('sync/from-sheets/', sync_from_sheets, name='sync_from_sheets'),

    # ── JBL Pipeline Portal ────────────────────────────────────────────────
    path('portal/', portal_home, name='portal_home'),
    path('portal/dashboard/', portal_dashboard, name='portal_dashboard'),
    path('portal/meta/', portal_meta, name='portal_meta'),
    # Stage 2 — JBL Visit
    path('portal/jbl-queue/', portal_jbl_queue, name='portal_jbl_queue'),
    path('portal/jbl-queue/<str:farmer_id>/', portal_log_jbl_visit, name='portal_log_jbl_visit'),
    # Stage 3 — Credit Decision
    path('portal/credit-queue/', portal_credit_queue, name='portal_credit_queue'),
    path('portal/credit-queue/<str:farmer_id>/', portal_set_credit_decision, name='portal_set_credit_decision'),
    # Stage 4 — Requisition / Order (GATED)
    path('portal/requisition-queue/', portal_requisition_queue, name='portal_requisition_queue'),
    path('portal/requisition-queue/generate/', portal_requisition_generate, name='portal_requisition_generate'),
    path('portal/requisition-queue/<str:farmer_id>/', portal_assign_order, name='portal_assign_order'),
    path('portal/requisition-batches/', portal_requisition_batches, name='portal_requisition_batches'),
    # All cases + deferred
    path('portal/farmers/', portal_all_cases, name='portal_all_cases'),
    path('portal/farmers/<str:farmer_id>/', portal_farmer_detail, name='portal_farmer_detail'),
    path('portal/deferred/', portal_deferred, name='portal_deferred'),
]
