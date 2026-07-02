"""
URL routing for the core API.
"""
from django.urls import path
from .views import (
    telegram_webhook,
    health_check,
    jawabu_farmers_review,
    jawabu_farmers_review_commit,
    order_approval_form,
    order_approval_webapp_lookup,
    order_approval_webapp_suggest,
    order_approval_webapp_submit,
    process_messages,
    resend_unsynced,
    sync_from_sheets,
)

urlpatterns = [
    path('health/', health_check, name='health_check'),
    path('order-approval/', order_approval_form, name='order_approval_form'),
    path('jawabu-farmers/review/', jawabu_farmers_review, name='jawabu_farmers_review'),
    path('jawabu-farmers/review/commit/', jawabu_farmers_review_commit, name='jawabu_farmers_review_commit'),
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
]
