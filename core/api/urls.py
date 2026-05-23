"""
URL routing for the core API.
"""
from django.urls import path
from .views import (
    telegram_webhook,
    health_check,
    order_approval_form,
    order_approval_webapp_submit,
    process_messages,
    resend_unsynced,
    sync_from_sheets,
)

urlpatterns = [
    path('health/', health_check, name='health_check'),
    path('order-approval/', order_approval_form, name='order_approval_form'),
    path('webhook/telegram/', telegram_webhook, name='telegram_webhook'),
    path(
        'order-approval/webapp/submit/',
        order_approval_webapp_submit,
        name='order_approval_webapp_submit',
    ),
    path('process/messages/', process_messages, name='process_messages'),
    path('resync/unsynced/', resend_unsynced, name='resend_unsynced'),
    path('sync/from-sheets/', sync_from_sheets, name='sync_from_sheets'),
]
