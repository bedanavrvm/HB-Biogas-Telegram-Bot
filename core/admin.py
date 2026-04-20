from django.contrib import admin
from .models import RawMessage, ProcessedMessage, ParsedMessage


@admin.register(RawMessage)
class RawMessageAdmin(admin.ModelAdmin):
    list_display = ['sender', 'received_at', 'has_image', 'created_at']
    list_filter = ['has_image', 'received_at']
    search_fields = ['sender', 'content']
    readonly_fields = ['id', 'created_at']


@admin.register(ProcessedMessage)
class ProcessedMessageAdmin(admin.ModelAdmin):
    list_display = ['message_hash', 'status', 'processed_at']
    list_filter = ['status', 'processed_at']
    search_fields = ['message_hash']
    readonly_fields = ['id', 'processed_at']


@admin.register(ParsedMessage)
class ParsedMessageAdmin(admin.ModelAdmin):
    list_display = [
        'message_id', 'sender', 'item', 'quantity', 
        'price', 'synced_to_sheets', 'timestamp'
    ]
    list_filter = ['synced_to_sheets', 'image_flag', 'timestamp']
    search_fields = ['sender', 'item', 'message_id']
    readonly_fields = ['id', 'created_at', 'synced_at']
