from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [('core', '0172_farmup_monthly_worklists'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name='OrderSequenceState',
            fields=[
                ('id', models.BigAutoField(db_comment='Internal sequence-state identifier.', primary_key=True, serialize=False)),
                ('next_number', models.PositiveBigIntegerField(db_comment='Next plain numeric order number available for finalization.')),
                ('revision', models.PositiveBigIntegerField(db_comment='Optimistic concurrency revision for sequence changes.', default=1)),
                ('adjustment_reason', models.TextField(blank=True, db_comment='Reason for the latest attributed sequence change.', default='')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_comment='Time this group sequence was initialized.')),
                ('updated_at', models.DateTimeField(auto_now=True, db_comment='Time the sequence was last adjusted or consumed.')),
                ('group_configuration', models.OneToOneField(db_comment='Jawabu group whose official paper numbering this sequence governs.', on_delete=django.db.models.deletion.PROTECT, related_name='requisition_order_sequence', to='core.groupsheetconfiguration')),
                ('updated_by', models.ForeignKey(blank=True, db_comment='Staff user who most recently adjusted or consumed the sequence.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Requisition order sequence',
                'verbose_name_plural': 'Requisition order sequences',
                'db_table': 'requisition_order_sequence_state',
                'db_table_comment': 'Group-scoped source of truth for the next official requisition order number.',
            },
        ),
        migrations.CreateModel(
            name='OrderSequenceEvent',
            fields=[
                ('id', models.BigAutoField(db_comment='Internal immutable event identifier.', primary_key=True, serialize=False)),
                ('action', models.CharField(db_comment='Whether IT adjusted or finalization consumed a number.', max_length=24)),
                ('number_before', models.PositiveBigIntegerField(db_comment='Next number immediately before the mutation.')),
                ('number_after', models.PositiveBigIntegerField(db_comment='Next number immediately after the mutation.')),
                ('revision_after', models.PositiveBigIntegerField(db_comment='Sequence revision committed by this mutation.')),
                ('reason', models.TextField(db_comment='Customer-data-free reason for the mutation.')),
                ('request_id', models.CharField(blank=True, db_comment='Idempotency key associated with the mutation.', db_index=True, default='', max_length=128)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_comment='Time the mutation committed.')),
                ('actor', models.ForeignKey(blank=True, db_comment='Staff user accountable for the mutation.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('sequence', models.ForeignKey(db_comment='Sequence changed by this event.', on_delete=django.db.models.deletion.PROTECT, related_name='events', to='requisitions.ordersequencestate')),
            ],
            options={'ordering': ['created_at', 'pk'], 'db_table': 'requisition_order_sequence_event', 'db_table_comment': 'Immutable customer-data-free audit trail for official requisition numbering.'},
        ),
        migrations.AddConstraint(model_name='ordersequenceevent', constraint=models.UniqueConstraint(condition=~models.Q(('request_id', '')), fields=('request_id',), name='unique_requisition_sequence_event_request')),
    ]
