#!/usr/bin/env python
"""
Django migration: Add multi-group support to ParsedMessage.

Adds group_id and sheet_id fields for multi-tenant tracking.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0004_add_production_schema_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='parsedmessage',
            name='group_id',
            field=models.CharField(
                max_length=255,
                blank=True,
                default='',
                db_index=True,
                help_text='Telegram chat_id for group/tenant identification'
            ),
        ),
        migrations.AddField(
            model_name='parsedmessage',
            name='sheet_id',
            field=models.CharField(
                max_length=255,
                blank=True,
                default='',
                help_text='Google Sheet ID for this message'
            ),
        ),
    ]
