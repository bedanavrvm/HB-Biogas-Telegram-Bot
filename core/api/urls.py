"""
URL routing for the core API.
"""
from django.urls import path
from .views import (
    telegram_webhook,
    health_check,
    process_messages,
    resend_unsynced,
)

urlpatterns = [
    path('health/', health_check, name='health_check'),
    path('webhook/telegram/', telegram_webhook, name='telegram_webhook'),
    path('process/messages/', process_messages, name='process_messages'),
    path('resync/unsynced/', resend_unsynced, name='resend_unsynced'),
]
