import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import uuid


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0185_hb_action_operations_read_access'),
        ('payments', '0003_payment_number_allocation_timing'),
    ]

    operations = [
        migrations.CreateModel(
            name='PaymentReceiptBatch',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False, db_comment='Immutable invoice delivery identifier.')),
                ('status', models.CharField(max_length=24, default='open', db_index=True, choices=[('open', 'Reconciling'), ('reconciled', 'Ready for payment'), ('payment_created', 'Payment batch created')], db_comment='Server-controlled reconciliation state for this invoice delivery.')),
                ('revision', models.PositiveBigIntegerField(default=1, db_comment='Optimistic concurrency revision for reconciliation changes.')),
                ('request_id', models.CharField(max_length=128, blank=True, default='', db_index=True, db_comment='Idempotency key for the source upload request.')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_comment='When the invoice delivery was received.')),
                ('updated_at', models.DateTimeField(auto_now=True, db_comment='When reconciliation was last changed.')),
                ('created_by', models.ForeignKey(null=True, blank=True, to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.SET_NULL, related_name='+', db_comment='Staff member who received the invoice delivery.')),
                ('group_configuration', models.ForeignKey(to='core.groupsheetconfiguration', on_delete=django.db.models.deletion.PROTECT, related_name='payment_receipt_batches', db_comment='Jawabu workflow configuration which received this invoice delivery.')),
            ],
            options={'db_table': 'payment_receipt_batch', 'db_table_comment': 'Authoritative multi-file HomeBiogas invoice delivery reconciled as one payment source.', 'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='PaymentReceiptItem',
            fields=[
                ('id', models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False, db_comment='Immutable receipt-item identifier.')),
                ('status', models.CharField(max_length=24, default='review', db_index=True, choices=[('matched', 'Matched and payable'), ('name_change', 'Invoice name change required'), ('review', 'Needs review'), ('parse_failed', 'Could not parse'), ('ignored', 'Ignored')], db_comment='Reconciliation disposition; only matched rows may become payment cases.')),
                ('reason', models.TextField(blank=True, default='', db_comment='Plain-language reason for a held or failed item.')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_comment='When this receipt item was created.')),
                ('updated_at', models.DateTimeField(auto_now=True, db_comment='When this receipt item last changed.')),
                ('farmer', models.ForeignKey(null=True, blank=True, to='core.jawabufarmermaster', on_delete=django.db.models.deletion.PROTECT, related_name='payment_receipt_items', db_comment='Proposed or matched contractual borrower.')),
                ('invoice', models.OneToOneField(null=True, blank=True, to='core.parsedinvoice', on_delete=django.db.models.deletion.PROTECT, related_name='payment_receipt_item', db_comment='Parsed invoice evidence; blank only for a source parse failure.')),
                ('receipt_batch', models.ForeignKey(to='payments.paymentreceiptbatch', on_delete=django.db.models.deletion.PROTECT, related_name='items', db_comment='Received invoice delivery containing this item.')),
                ('replacement_invoice', models.ForeignKey(null=True, blank=True, to='core.parsedinvoice', on_delete=django.db.models.deletion.PROTECT, related_name='+', db_comment='Corrected invoice explicitly attached to this held source invoice.')),
                ('source_upload', models.ForeignKey(to='core.invoiceuploadbatch', on_delete=django.db.models.deletion.PROTECT, related_name='payment_receipt_items', db_comment='Original uploaded PDF evidence for this item.')),
            ],
            options={'db_table': 'payment_receipt_item', 'db_table_comment': 'Per-invoice payment reconciliation result, including non-payable held rows.'},
        ),
        migrations.AddField(
            model_name='paymentbatch', name='receipt_batch',
            field=models.OneToOneField(null=True, blank=True, to='payments.paymentreceiptbatch', on_delete=django.db.models.deletion.PROTECT, related_name='payment_batch', db_comment='Optional invoice receipt bundle from which this governed payment batch was prepared.'),
        ),
        migrations.AddConstraint(model_name='paymentreceiptbatch', constraint=models.UniqueConstraint(fields=('request_id',), condition=models.Q(('request_id', ''), _negated=True), name='payment_receipt_batch_request_unique')),
        migrations.AddConstraint(model_name='paymentreceiptitem', constraint=models.UniqueConstraint(fields=('receipt_batch', 'source_upload', 'invoice'), name='payment_receipt_item_source_invoice_unique')),
        migrations.AddIndex(model_name='paymentreceiptbatch', index=models.Index(fields=['group_configuration', 'status'], name='payrcpt_group_status_idx')),
        migrations.AddIndex(model_name='paymentreceiptitem', index=models.Index(fields=['receipt_batch', 'status'], name='payrcpt_item_batch_status_idx')),
    ]
