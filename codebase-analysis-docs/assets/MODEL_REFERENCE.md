# Static model reference

Declared fields only; abstract inheritance, runtime registration, implicit Django fields, and migration state require checking authoritative model code and migrations. This is not a live database dump.

## core/models.py::RawMessage

[[F:core/models.py#28-57#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
telegram_message_id | models.CharField |  | max_length=255; db_index=True
source_telegram_message_id | models.CharField |  | max_length=255; blank=True; db_index=True
batch_index | models.PositiveIntegerField |  | null=True; blank=True
sender | models.CharField |  | max_length=255; blank=True
content | models.TextField |  | 
received_at | models.DateTimeField |  | 
has_image | models.BooleanField |  | 
created_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-received_at']", "indexes": "[models.Index(fields=['telegram_message_id', 'received_at']), models.Index(fields=['source_telegram_message_id', 'received_at'])]"}`

## core/models.py::ProcessedMessage

[[F:core/models.py#60-86#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
message_hash | models.CharField |  | max_length=128; unique=True; db_index=True
raw_message | models.ForeignKey | RawMessage | on_delete=models.CASCADE; related_name='processed_records'
processed_at | models.DateTimeField |  | 
status | models.CharField |  | max_length=20; choices=STATUS_CHOICES
error_message | models.TextField |  | blank=True

Model metadata: `{"ordering": "['-processed_at']"}`

## core/models.py::ParsedMessage

[[F:core/models.py#89-225#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
processed_message | models.ForeignKey | ProcessedMessage | on_delete=models.CASCADE; related_name='parsed_records'
message_id | models.CharField |  | max_length=128; db_index=True
timestamp | models.DateTimeField |  | null=True; blank=True
sender | models.CharField |  | max_length=255; blank=True
raw_message | models.TextField |  | 
item | models.CharField |  | max_length=255; blank=True
quantity | models.DecimalField |  | max_digits=10; decimal_places=2; null=True; blank=True
price | models.DecimalField |  | max_digits=10; decimal_places=2; null=True; blank=True
gps_link | models.URLField |  | max_length=500; blank=True
image_flag | models.BooleanField |  | 
source | models.CharField |  | max_length=50
customer_name | models.CharField |  | max_length=255; blank=True
customer_phone | models.CharField |  | max_length=255; blank=True
secondary_phone | models.CharField |  | max_length=255; blank=True
customer_id | models.CharField |  | max_length=255; blank=True
county | models.CharField |  | max_length=128; blank=True
sub_county | models.CharField |  | max_length=128; blank=True
village | models.CharField |  | max_length=255; blank=True
branch_region | models.CharField |  | max_length=255; blank=True
complaint_category | models.CharField |  | max_length=255; blank=True
complaint_description | models.TextField |  | blank=True
complaint_status | models.CharField |  | max_length=255; blank=True
resolution_details | models.TextField |  | blank=True
date_resolved | models.DateTimeField |  | null=True; blank=True
days_open | models.IntegerField |  | null=True; blank=True
risk_level | models.CharField |  | max_length=100; blank=True
loan_status | models.CharField |  | max_length=100; blank=True
loan_at_risk | models.CharField |  | max_length=100; blank=True
group_id | models.CharField |  | max_length=100; db_index=True
sheet_id | models.CharField |  | max_length=255; blank=True; db_index=True
sheet_name | models.CharField |  | max_length=255; blank=True
synced_to_sheets | models.BooleanField |  | 
synced_at | models.DateTimeField |  | null=True; blank=True
sync_attempts | models.IntegerField |  | 
last_sync_error | models.TextField |  | blank=True
created_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-timestamp']", "constraints": "[models.UniqueConstraint(fields=['group_id', 'message_id'], name='unique_case_message_per_group')]", "indexes": "[models.Index(fields=['group_id', 'sheet_id']), models.Index(fields=['synced_to_sheets']), models.Index(fields=['complaint_status', 'timestamp'], name='core_parsed_complaint_time_idx')]"}`

## core/models.py::CaseUpdate

[[F:core/models.py#228-286#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
parsed_message | models.ForeignKey | ParsedMessage | on_delete=models.CASCADE; related_name='case_updates'
group_id | models.CharField |  | max_length=100; db_index=True
updated_by | models.CharField |  | max_length=255; blank=True
telegram_message_id | models.CharField |  | max_length=255; blank=True
reply_to_telegram_message_id | models.CharField |  | max_length=255; blank=True
old_status | models.CharField |  | max_length=255; blank=True
new_status | models.CharField |  | max_length=255; blank=True
resolution_text | models.TextField |  | blank=True
risk_level | models.CharField |  | max_length=100; blank=True
loan_at_risk | models.CharField |  | max_length=100; blank=True
sync_status | models.CharField |  | max_length=20; choices=SYNC_STATUS_CHOICES
sync_error | models.TextField |  | blank=True
raw_update_text | models.TextField |  | 
source | models.CharField |  | max_length=50
client_request_id | models.CharField |  | max_length=128; blank=True; db_index=True
gps_link | models.URLField |  | max_length=500; blank=True
latitude | models.DecimalField |  | max_digits=9; decimal_places=6; null=True; blank=True
longitude | models.DecimalField |  | max_digits=9; decimal_places=6; null=True; blank=True
created_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-created_at']", "indexes": "[models.Index(fields=['group_id', 'created_at']), models.Index(fields=['telegram_message_id']), models.Index(fields=['reply_to_telegram_message_id']), models.Index(fields=['parsed_message', 'client_request_id'])]", "constraints": "[models.UniqueConstraint(fields=['parsed_message', 'client_request_id'], condition=~models.Q(client_request_id=''), name='unique_complaint_case_update_request')]"}`

## core/models.py::ComplaintCaseSequence

[[F:core/models.py#289-305#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
group_id | models.CharField |  | max_length=100; db_index=True
year | models.PositiveIntegerField |  | db_index=True
next_number | models.PositiveIntegerField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"constraints": "[models.UniqueConstraint(fields=['group_id', 'year'], name='unique_complaint_sequence_group_year')]"}`

## core/models.py::ComplaintCaseEvidence

[[F:core/models.py#308-349#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
parsed_message | models.ForeignKey | ParsedMessage | on_delete=models.CASCADE; related_name='complaint_evidence'
case_update | models.ForeignKey | CaseUpdate | on_delete=models.CASCADE; related_name='evidence'
group_id | models.CharField |  | max_length=100; db_index=True
uploaded_by | models.CharField |  | max_length=255; blank=True
original_filename | models.CharField |  | max_length=255; blank=True
storage_filename | models.CharField |  | max_length=255; blank=True
mime_type | models.CharField |  | max_length=255; blank=True
size | models.PositiveIntegerField |  | null=True; blank=True
content_hash | models.CharField |  | max_length=64; blank=True; db_index=True
drive_file_id | models.CharField |  | max_length=255; blank=True
drive_url | models.URLField |  | max_length=1000; blank=True
upload_status | models.CharField |  | max_length=20; choices=STATUS_CHOICES
upload_error | models.TextField |  | blank=True
created_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-created_at']", "indexes": "[models.Index(fields=['parsed_message', 'created_at']), models.Index(fields=['group_id', 'upload_status'])]"}`

## core/models.py::ComplaintCategory

[[F:core/models.py#352-389#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
key | models.SlugField |  | max_length=80; unique=True
label | models.CharField |  | max_length=160
description | models.TextField |  | blank=True
default_priority | models.CharField |  | max_length=10; choices=PRIORITY_CHOICES
default_sla_hours | models.PositiveIntegerField |  | 
active | models.BooleanField |  | db_index=True
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='+'
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['label']", "constraints": "[models.UniqueConstraint(Lower('label'), name='unique_complaint_category_label_ci'), models.CheckConstraint(condition=models.Q(default_sla_hours__gt=0), name='complaint_category_sla_positive')]"}`

## core/models.py::ComplaintCategoryAlias

[[F:core/models.py#392-411#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
category | models.ForeignKey | ComplaintCategory | on_delete=models.PROTECT; related_name='aliases'
alias | models.CharField |  | max_length=160
normalized_alias | models.CharField |  | max_length=180; unique=True
active | models.BooleanField |  | db_index=True
created_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['alias']"}`

## core/models.py::ComplaintCategoryAvailability

[[F:core/models.py#414-430#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
category | models.ForeignKey | ComplaintCategory | on_delete=models.CASCADE; related_name='availability'
group_configuration | models.ForeignKey | 'GroupSheetConfiguration' | on_delete=models.CASCADE; related_name='complaint_category_availability'
active | models.BooleanField |  | db_index=True
created_at | models.DateTimeField |  | 

Model metadata: `{"constraints": "[models.UniqueConstraint(fields=['category', 'group_configuration'], name='unique_complaint_category_group')]"}`

## core/models.py::ComplaintCaseControl

[[F:core/models.py#433-503#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
parsed_message | models.OneToOneField | ParsedMessage | on_delete=models.CASCADE; related_name='complaint_control'
reference_number | models.CharField |  | max_length=16; unique=True; null=True; blank=True; db_index=True
category | models.ForeignKey | ComplaintCategory | null=True; blank=True; on_delete=models.PROTECT; related_name='cases'
branch_ref | models.ForeignKey | 'OperationalLocation' | null=True; blank=True; on_delete=models.PROTECT; related_name='complaint_cases'
county_ref | models.ForeignKey | 'OperationalLocation' | null=True; blank=True; on_delete=models.PROTECT; related_name='complaint_county_cases'
sub_county_ref | models.ForeignKey | 'OperationalLocation' | null=True; blank=True; on_delete=models.PROTECT; related_name='complaint_sub_county_cases'
customer | models.ForeignKey | 'JawabuCustomer' | null=True; blank=True; on_delete=models.SET_NULL; related_name='complaint_cases'
customer_match_status | models.CharField |  | max_length=20; choices=MATCH_CHOICES
assigned_to | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='assigned_complaint_cases'
assigned_at | models.DateTimeField |  | null=True; blank=True
priority | models.CharField |  | max_length=10; choices=PRIORITY_CHOICES; db_index=True
sla_target_hours | models.PositiveIntegerField |  | 
sla_started_at | models.DateTimeField |  | 
sla_due_at | models.DateTimeField |  | null=True; blank=True; db_index=True
revision | models.PositiveIntegerField |  | 
sync_status | models.CharField |  | max_length=20; choices=SYNC_CHOICES; db_index=True
sync_error | models.TextField |  | blank=True
last_sync_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-sla_due_at']", "indexes": "[models.Index(fields=['assigned_to', 'priority']), models.Index(fields=['sync_status', 'updated_at'])]", "constraints": "[models.CheckConstraint(condition=models.Q(revision__gt=0), name='complaint_case_revision_positive'), models.CheckConstraint(condition=models.Q(sla_target_hours__gt=0), name='complaint_case_sla_positive')]"}`

## core/models.py::ComplaintCaseEvent

[[F:core/models.py#506-538#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
case | models.ForeignKey | ComplaintCaseControl | on_delete=models.PROTECT; related_name='events'
revision | models.PositiveIntegerField |  | 
action | models.CharField |  | max_length=80; db_index=True
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='+'
actor_label | models.CharField |  | max_length=255; blank=True
request_id | models.CharField |  | max_length=128; blank=True; db_index=True
payload_hash | models.CharField |  | max_length=64; blank=True; db_index=True
before_values | models.JSONField |  | blank=True
after_values | models.JSONField |  | blank=True
reason | models.TextField |  | blank=True
created_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-created_at']", "constraints": "[models.UniqueConstraint(fields=['case', 'request_id'], condition=~models.Q(request_id=''), name='unique_complaint_case_event_request')]", "indexes": "[models.Index(fields=['case', 'revision'])]"}`

## core/models.py::ComplaintCaseImportBatch

[[F:core/models.py#541-599#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
group_id | models.CharField |  | max_length=100; db_index=True
source_telegram_message_id | models.CharField |  | max_length=255
initiated_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='complaint_case_import_batches'
actor_label | models.CharField |  | max_length=255; blank=True
telegram_user_id_snapshot | models.CharField |  | max_length=64; blank=True
source_hash | models.CharField |  | max_length=64; db_index=True
status | models.CharField |  | max_length=16; choices=STATUS_CHOICES; db_index=True
analysis_snapshot | models.JSONField |  | blank=True
source_count | models.PositiveIntegerField |  | 
created_count | models.PositiveIntegerField |  | 
matched_count | models.PositiveIntegerField |  | 
rejected_count | models.PositiveIntegerField |  | 
error_count | models.PositiveIntegerField |  | 
attempt_count | models.PositiveIntegerField |  | 
lease_token | models.UUIDField |  | null=True; blank=True; db_index=True
heartbeat_at | models.DateTimeField |  | null=True; blank=True; db_index=True
last_error_code | models.CharField |  | max_length=80; blank=True
started_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 
completed_at | models.DateTimeField |  | null=True; blank=True

Model metadata: `{"ordering": "['-created_at']", "indexes": "[models.Index(fields=['status', 'created_at'], name='cc_import_status_created_idx')]", "constraints": "[models.UniqueConstraint(fields=['group_id', 'source_telegram_message_id'], name='unique_complaint_import_source_message')]"}`

## core/models.py::ComplaintCaseImportItem

[[F:core/models.py#602-650#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
batch | models.ForeignKey | ComplaintCaseImportBatch | on_delete=models.PROTECT; related_name='items'
parsed_message | models.OneToOneField | ParsedMessage | null=True; blank=True; on_delete=models.PROTECT; related_name='complaint_import_item'
source_index | models.PositiveIntegerField |  | 
normalized_entry_snapshot | models.JSONField |  | blank=True
content_hash | models.CharField |  | max_length=64; blank=True; db_index=True
status | models.CharField |  | max_length=16; choices=STATUS_CHOICES; db_index=True
attempt_count | models.PositiveIntegerField |  | 
last_error_code | models.CharField |  | max_length=80; blank=True
outcome_reference | models.CharField |  | max_length=128; blank=True; db_index=True
started_at | models.DateTimeField |  | null=True; blank=True
completed_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['source_index']", "indexes": "[models.Index(fields=['batch', 'status', 'source_index'], name='cc_item_batch_status_idx')]", "constraints": "[models.UniqueConstraint(fields=['batch', 'source_index'], name='unique_complaint_import_source_index')]"}`

## core/models.py::OrderApprovalUpdate

[[F:core/models.py#653-715#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
group_id | models.CharField |  | max_length=100; db_index=True
sheet_id | models.CharField |  | max_length=255; blank=True; db_index=True
sheet_tab | models.CharField |  | max_length=255; blank=True
row_number | models.PositiveIntegerField |  | null=True; blank=True
id_number | models.CharField |  | max_length=255; blank=True; db_index=True
sender | models.CharField |  | max_length=255; blank=True
telegram_message_id | models.CharField |  | max_length=255; blank=True; db_index=True
client_request_id | models.CharField |  | max_length=128; blank=True; db_index=True
request_fingerprint | models.CharField |  | max_length=64; blank=True
response_snapshot | models.JSONField |  | blank=True
reply_to_telegram_message_id | models.CharField |  | max_length=255; blank=True
raw_text | models.TextField |  | blank=True
parsed_fields | models.JSONField |  | blank=True
branch_ref | models.ForeignKey | 'OperationalLocation' | null=True; blank=True; on_delete=models.PROTECT; related_name='order_approval_branch_updates'
county_ref | models.ForeignKey | 'OperationalLocation' | null=True; blank=True; on_delete=models.PROTECT; related_name='order_approval_county_updates'
sub_county_ref | models.ForeignKey | 'OperationalLocation' | null=True; blank=True; on_delete=models.PROTECT; related_name='order_approval_sub_county_updates'
location_snapshot | models.JSONField |  | blank=True
update_status | models.CharField |  | max_length=20; choices=STATUS_CHOICES
sync_error | models.TextField |  | blank=True
created_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-created_at']", "indexes": "[models.Index(fields=['group_id', 'created_at']), models.Index(fields=['group_id', 'id_number'])]", "constraints": "[models.UniqueConstraint(fields=['group_id', 'client_request_id'], condition=~models.Q(client_request_id=''), name='unique_order_approval_client_request')]"}`

## core/models.py::MediaAttachment

[[F:core/models.py#718-783#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
order_update | models.ForeignKey | OrderApprovalUpdate | on_delete=models.SET_NULL; null=True; blank=True; related_name='media_attachments'
group_id | models.CharField |  | max_length=100; db_index=True
telegram_message_id | models.CharField |  | max_length=255; blank=True; db_index=True
reply_to_telegram_message_id | models.CharField |  | max_length=255; blank=True
telegram_file_id | models.CharField |  | max_length=255; blank=True; db_index=True
sender | models.CharField |  | max_length=255; blank=True
file_type | models.CharField |  | max_length=50; blank=True
original_filename | models.CharField |  | max_length=255; blank=True
mime_type | models.CharField |  | max_length=255; blank=True
size | models.PositiveIntegerField |  | null=True; blank=True
content_hash | models.CharField |  | max_length=64; blank=True; db_index=True
storage_provider | models.CharField |  | max_length=50; blank=True
drive_file_id | models.CharField |  | max_length=255; blank=True
drive_url | models.URLField |  | max_length=1000; blank=True
upload_status | models.CharField |  | max_length=20; choices=STATUS_CHOICES
upload_error | models.TextField |  | blank=True
business_key_type | models.CharField |  | max_length=100; blank=True
business_key_value | models.CharField |  | max_length=255; blank=True; db_index=True
jawabu_farmer | models.ForeignKey | 'JawabuFarmerMaster' | null=True; blank=True; on_delete=models.PROTECT; related_name='media_attachments'
portal_operation_id | models.CharField |  | max_length=128; blank=True; db_index=True
captured_at | models.DateTimeField |  | null=True; blank=True
capture_latitude | models.DecimalField |  | max_digits=9; decimal_places=6; null=True; blank=True
capture_longitude | models.DecimalField |  | max_digits=9; decimal_places=6; null=True; blank=True
capture_location_unavailable_reason | models.CharField |  | max_length=255; blank=True
created_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-created_at']", "indexes": "[models.Index(fields=['group_id', 'created_at']), models.Index(fields=['business_key_type', 'business_key_value']), models.Index(fields=['jawabu_farmer', 'file_type', 'upload_status'])]"}`

## core/models.py::SpinCreditRequest

[[F:core/models.py#786-915#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
data_mode | models.CharField |  | max_length=16; choices=WORKFLOW_DATA_MODE_CHOICES; db_index=True
pilot_cycle_id | models.UUIDField |  | null=True; blank=True; db_index=True
data_scope_key | models.CharField |  | max_length=64; db_index=True
group_id | models.CharField |  | max_length=100; db_index=True
sheet_id | models.CharField |  | max_length=255; blank=True; db_index=True
sheet_name | models.CharField |  | max_length=255; blank=True
row_number | models.PositiveIntegerField |  | null=True; blank=True
public_sequence_year | models.PositiveIntegerField |  | null=True; blank=True; db_index=True
public_sequence_number | models.PositiveIntegerField |  | null=True; blank=True; db_index=True
telegram_message_id | models.CharField |  | max_length=255; blank=True; db_index=True
source_message_hash | models.CharField |  | max_length=64; blank=True; db_index=True
source_chat | models.CharField |  | max_length=255; blank=True
source_filename | models.CharField |  | max_length=255; blank=True
source_message_index | models.PositiveIntegerField |  | null=True; blank=True
request_datetime | models.DateTimeField |  | null=True; blank=True; db_index=True
requested_by | models.CharField |  | max_length=255; blank=True
request_type | models.CharField |  | max_length=40; choices=REQUEST_TYPE_CHOICES; db_index=True
customer_name | models.CharField |  | max_length=255; blank=True; db_index=True
national_id | models.CharField |  | max_length=100; blank=True; db_index=True
raw_id_text | models.CharField |  | max_length=255; blank=True
primary_phone | models.CharField |  | max_length=50; blank=True; db_index=True
secondary_phone | models.CharField |  | max_length=50; blank=True
customer_type | models.CharField |  | max_length=50; blank=True
loan_product | models.CharField |  | max_length=255; blank=True
product | models.ForeignKey | 'Product' | null=True; blank=True; on_delete=models.PROTECT; related_name='spin_credit_requests'
product_version | models.ForeignKey | 'ProductVersion' | null=True; blank=True; on_delete=models.PROTECT; related_name='spin_credit_requests'
product_terms_snapshot | models.JSONField |  | blank=True
product_quote_snapshot | models.JSONField |  | blank=True
product_requirement_evidence | models.JSONField |  | blank=True
product_custom_values | models.JSONField |  | blank=True
product_selected_fee_keys | models.JSONField |  | blank=True
requested_amount | models.DecimalField |  | max_digits=12; decimal_places=2; null=True; blank=True
tenor | models.CharField |  | max_length=100; blank=True
business_notes | models.TextField |  | blank=True
code | models.CharField |  | max_length=255; blank=True
attachment_names | models.JSONField |  | blank=True
raw_message | models.TextField |  | blank=True
parsed_fields | models.JSONField |  | blank=True
missing_fields | models.JSONField |  | blank=True
import_status | models.CharField |  | max_length=30; choices=IMPORT_STATUS_CHOICES; db_index=True
sync_error | models.TextField |  | blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-request_datetime', '-created_at']", "indexes": "[models.Index(fields=['group_id', 'request_datetime']), models.Index(fields=['group_id', 'public_sequence_year', 'public_sequence_number']), models.Index(fields=['group_id', 'national_id', 'primary_phone']), models.Index(fields=['group_id', 'import_status']), models.Index(fields=['data_mode', 'pilot_cycle_id', 'created_at'])]", "constraints": "[models.UniqueConstraint(fields=['group_id', 'source_message_hash', 'data_scope_key'], name='unique_spin_request_source_per_group'), models.UniqueConstraint(fields=['group_id', 'public_sequence_year', 'public_sequence_number'], condition=models.Q(public_sequence_number__isnull=False), name='unique_spin_public_sequence_per_group_year')]"}`

## core/models.py::SpinBatchReviewItem

[[F:core/models.py#918-988#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
data_mode | models.CharField |  | max_length=16; choices=WORKFLOW_DATA_MODE_CHOICES; db_index=True
pilot_cycle_id | models.UUIDField |  | null=True; blank=True; db_index=True
data_scope_key | models.CharField |  | max_length=64; db_index=True
group_id | models.CharField |  | max_length=100; db_index=True
telegram_message_id | models.CharField |  | max_length=255; blank=True; db_index=True
source_message_hash | models.CharField |  | max_length=64; db_index=True
source_filename | models.CharField |  | max_length=255; blank=True
source_message_index | models.PositiveIntegerField |  | null=True; blank=True
source_sender | models.CharField |  | max_length=255; blank=True
source_received_at | models.DateTimeField |  | null=True; blank=True
raw_message | models.TextField |  | 
category | models.CharField |  | max_length=30; choices=CATEGORY_CHOICES; db_index=True
reason | models.TextField |  | blank=True
detected_fields | models.JSONField |  | blank=True
candidate_fields | models.JSONField |  | blank=True
status | models.CharField |  | max_length=20; choices=STATUS_CHOICES; db_index=True
resolved_request | models.ForeignKey | SpinCreditRequest | null=True; blank=True; on_delete=models.SET_NULL; related_name='resolved_batch_review_items'
resolution_fields | models.JSONField |  | blank=True
reviewed_by | models.CharField |  | max_length=255; blank=True
reviewed_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-source_received_at', '-created_at']", "constraints": "[models.UniqueConstraint(fields=['group_id', 'source_message_hash', 'data_scope_key'], name='unique_spin_batch_review_source_per_group')]", "indexes": "[models.Index(fields=['group_id', 'status', 'created_at']), models.Index(fields=['group_id', 'category', 'status']), models.Index(fields=['data_mode', 'pilot_cycle_id', 'created_at'])]"}`

## core/models.py::SpinRequestSequence

[[F:core/models.py#991-1007#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
group_id | models.CharField |  | max_length=100; db_index=True
year | models.PositiveIntegerField |  | db_index=True
next_number | models.PositiveIntegerField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"constraints": "[models.UniqueConstraint(fields=['group_id', 'year'], name='unique_spin_sequence_group_year')]"}`

## core/models.py::TatTrackerCase

[[F:core/models.py#1009-1137#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
data_mode | models.CharField |  | max_length=16; choices=WORKFLOW_DATA_MODE_CHOICES; db_index=True
pilot_cycle_id | models.UUIDField |  | null=True; blank=True; db_index=True
data_scope_key | models.CharField |  | max_length=64; db_index=True
group_id | models.CharField |  | max_length=100; db_index=True
sheet_id | models.CharField |  | max_length=255; blank=True; db_index=True
sheet_name | models.CharField |  | max_length=255; blank=True; db_index=True
row_number | models.PositiveIntegerField |  | null=True; blank=True
create_request_id | models.CharField |  | max_length=128; blank=True; db_index=True
case_id | models.CharField |  | max_length=128; db_index=True
product_key | models.CharField |  | max_length=80; db_index=True
product_label | models.CharField |  | max_length=120; blank=True
product | models.ForeignKey | 'Product' | null=True; blank=True; on_delete=models.PROTECT; related_name='tat_cases'
product_version | models.ForeignKey | 'ProductVersion' | null=True; blank=True; on_delete=models.PROTECT; related_name='tat_cases'
product_terms_snapshot | models.JSONField |  | blank=True
tat_configuration_snapshot | models.JSONField |  | blank=True
configuration_binding_status | models.CharField |  | max_length=24; choices=CONFIG_BINDING_CHOICES; db_index=True
product_quote_snapshot | models.JSONField |  | blank=True
product_requirement_evidence | models.JSONField |  | blank=True
product_custom_values | models.JSONField |  | blank=True
product_selected_fee_keys | models.JSONField |  | blank=True
client_name | models.CharField |  | max_length=255; db_index=True
national_id | models.CharField |  | max_length=32; blank=True; db_index=True
primary_phone | models.CharField |  | max_length=32; blank=True; db_index=True
branch | models.CharField |  | max_length=120; blank=True; db_index=True
bro_name | models.CharField |  | max_length=255; blank=True
amount | models.DecimalField |  | max_digits=14; decimal_places=2; null=True; blank=True
final_loan_amount | models.DecimalField |  | max_digits=14; decimal_places=2; null=True; blank=True
stage_values | models.JSONField |  | blank=True
stage_target_snapshots | models.JSONField |  | blank=True
status | models.CharField |  | max_length=40; choices=STATUS_CHOICES; db_index=True
remarks | models.TextField |  | blank=True
current_stage | models.CharField |  | max_length=120; blank=True; db_index=True
workflow_revision | models.PositiveIntegerField |  | 
created_by | models.CharField |  | max_length=255; blank=True
created_by_telegram_id | models.CharField |  | max_length=100; blank=True; db_index=True
last_updated_by | models.CharField |  | max_length=255; blank=True
last_synced_at | models.DateTimeField |  | null=True; blank=True
sync_error | models.TextField |  | blank=True
is_deleted | models.BooleanField |  | db_index=True
deleted_at | models.DateTimeField |  | null=True; blank=True
deleted_by | models.CharField |  | max_length=255; blank=True
deletion_reason | models.TextField |  | blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-created_at']", "constraints": "[models.UniqueConstraint(fields=['group_id', 'case_id'], name='unique_tat_case_id_per_group'), models.UniqueConstraint(fields=['group_id', 'create_request_id', 'data_scope_key'], condition=~models.Q(create_request_id=''), name='unique_tat_create_request_per_group')]", "indexes": "[models.Index(fields=['group_id', 'status']), models.Index(fields=['group_id', 'product_key', 'status']), models.Index(fields=['group_id', 'client_name']), models.Index(fields=['group_id', 'current_stage']), models.Index(fields=['group_id', 'is_deleted']), models.Index(fields=['data_mode', 'pilot_cycle_id', 'created_at'])]"}`

## core/models.py::TatTrackerEvent

[[F:core/models.py#1140-1206#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
case | models.ForeignKey | TatTrackerCase | on_delete=models.CASCADE; related_name='events'
group_id | models.CharField |  | max_length=100; db_index=True
actor_name | models.CharField |  | max_length=255; blank=True
actor_telegram_id | models.CharField |  | max_length=100; blank=True; db_index=True
actor_role | models.CharField |  | max_length=255; blank=True
actor_user | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='tat_tracker_actions'
authority_user | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='tat_tracker_authorized_actions'
stage_key | models.CharField |  | max_length=120; blank=True; db_index=True
stage_label | models.CharField |  | max_length=160; blank=True
old_value | models.TextField |  | blank=True
new_value | models.TextField |  | blank=True
source | models.CharField |  | max_length=40; choices=SOURCE_CHOICES; db_index=True
request_id | models.CharField |  | max_length=128; blank=True; db_index=True
transition_code | models.CharField |  | max_length=120; blank=True; db_index=True
from_state | models.CharField |  | max_length=120; blank=True; db_index=True
to_state | models.CharField |  | max_length=120; blank=True; db_index=True
reason | models.TextField |  | blank=True
revision_before | models.PositiveIntegerField |  | null=True; blank=True
revision_after | models.PositiveIntegerField |  | null=True; blank=True
sheet_name | models.CharField |  | max_length=255; blank=True
row_number | models.PositiveIntegerField |  | null=True; blank=True
sync_error | models.TextField |  | blank=True
synced_to_sheet | models.BooleanField |  | db_index=True
synced_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-created_at']", "constraints": "[models.UniqueConstraint(fields=['case', 'request_id'], condition=~models.Q(request_id=''), name='unique_tat_event_request_per_case')]", "indexes": "[models.Index(fields=['group_id', 'created_at']), models.Index(fields=['group_id', 'stage_key']), models.Index(fields=['case', 'created_at'])]"}`

## core/models.py::TatResponsibilityAssignment

[[F:core/models.py#1209-1293#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
group_configuration | models.ForeignKey | 'GroupSheetConfiguration' | on_delete=models.CASCADE; related_name='tat_responsibility_assignments'
branch | models.CharField |  | max_length=120; db_index=True
role | models.CharField |  | max_length=80; db_index=True
product_key | models.CharField |  | max_length=80; blank=True; db_index=True
stage_key | models.CharField |  | max_length=120; blank=True; db_index=True
primary_user | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='primary_tat_responsibilities'
active | models.BooleanField |  | db_index=True
effective_from | models.DateTimeField |  | db_index=True
effective_until | models.DateTimeField |  | null=True; blank=True; db_index=True
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='created_tat_responsibilities'
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['group_configuration', 'branch', 'role', '-stage_key', '-product_key']", "constraints": "[models.UniqueConstraint(fields=['group_configuration', 'branch', 'role', 'product_key', 'stage_key'], condition=models.Q(active=True), name='unique_active_tat_responsibility')]", "indexes": "[models.Index(fields=['group_configuration', 'branch', 'role', 'active'])]"}`

## core/models.py::TatResponsibilityBackup

[[F:core/models.py#1296-1370#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
assignment | models.ForeignKey | TatResponsibilityAssignment | on_delete=models.CASCADE; related_name='backups'
user | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='backup_tat_responsibilities'
rank | models.PositiveSmallIntegerField |  | 
threshold_percent | models.PositiveSmallIntegerField |  | 
active | models.BooleanField |  | db_index=True
created_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['rank', 'created_at']", "constraints": "[models.UniqueConstraint(fields=['assignment', 'rank'], name='unique_tat_backup_rank'), models.UniqueConstraint(fields=['assignment', 'user'], name='unique_tat_backup_user'), models.CheckConstraint(condition=models.Q(rank__gte=1), name='tat_backup_rank_positive'), models.CheckConstraint(condition=models.Q(threshold_percent__gte=1), name='tat_backup_threshold_positive')]"}`

## core/models.py::TatResponsibilityEvent

[[F:core/models.py#1373-1410#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
assignment | models.ForeignKey | TatResponsibilityAssignment | null=True; blank=True; on_delete=models.SET_NULL; related_name='events'
assignment_id_snapshot | models.UUIDField |  | db_index=True
action | models.CharField |  | max_length=32; choices=ACTION_CHOICES; db_index=True
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='tat_responsibility_events'
reason | models.TextField |  | blank=True
before_snapshot | models.JSONField |  | blank=True
after_snapshot | models.JSONField |  | blank=True
created_at | models.DateTimeField |  | db_index=True

Model metadata: `{"ordering": "['-created_at']", "indexes": "[models.Index(fields=['assignment_id_snapshot', 'created_at'], name='tat_resp_evt_assign_idx')]"}`

## core/models.py::TatPrivateAlertConnection

[[F:core/models.py#1413-1448#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
user | models.OneToOneField | settings.AUTH_USER_MODEL | on_delete=models.CASCADE; related_name='tat_private_alert_connection'
status | models.CharField |  | max_length=24; choices=STATUS_CHOICES; db_index=True
connected_at | models.DateTimeField |  | null=True; blank=True
disconnected_at | models.DateTimeField |  | null=True; blank=True
last_success_at | models.DateTimeField |  | null=True; blank=True
last_failure_at | models.DateTimeField |  | null=True; blank=True
last_failure_code | models.CharField |  | max_length=80; blank=True
last_connect_request_id | models.CharField |  | max_length=128; blank=True
last_disconnect_request_id | models.CharField |  | max_length=128; blank=True
last_test_request_id | models.CharField |  | max_length=128; blank=True
updated_at | models.DateTimeField |  | 

Model metadata: `{}`

## core/models.py::TatPrivateAlertConnectionEvent

[[F:core/models.py#1451-1494#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
connection | models.ForeignKey | TatPrivateAlertConnection | null=True; blank=True; on_delete=models.SET_NULL; related_name='events'
connection_id_snapshot | models.CharField |  | max_length=64; blank=True; db_index=True
user_id_snapshot | models.CharField |  | max_length=64; blank=True; db_index=True
username_snapshot | models.CharField |  | max_length=150; blank=True
actor_id_snapshot | models.CharField |  | max_length=64; blank=True
actor_username_snapshot | models.CharField |  | max_length=150; blank=True
event_type | models.CharField |  | max_length=32; choices=EVENT_CHOICES; db_index=True
status | models.CharField |  | max_length=24; choices=TatPrivateAlertConnection.STATUS_CHOICES
source | models.CharField |  | max_length=32; blank=True; db_index=True
request_id | models.CharField |  | max_length=128; blank=True; db_index=True
detail_code | models.CharField |  | max_length=80; blank=True
created_at | models.DateTimeField |  | db_index=True

Model metadata: `{"ordering": "['-created_at']", "constraints": "[models.UniqueConstraint(fields=['request_id'], condition=~models.Q(request_id=''), name='unique_tat_alert_event_request')]"}`

## core/models.py::TatActionTask

[[F:core/models.py#1497-1553#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
case | models.ForeignKey | TatTrackerCase | on_delete=models.CASCADE; related_name='action_tasks'
group_configuration | models.ForeignKey | 'GroupSheetConfiguration' | null=True; blank=True; on_delete=models.SET_NULL; related_name='tat_action_tasks'
assignment | models.ForeignKey | TatResponsibilityAssignment | null=True; blank=True; on_delete=models.SET_NULL; related_name='tasks'
stage_key | models.CharField |  | max_length=120; db_index=True
stage_label | models.CharField |  | max_length=160
responsible_role | models.CharField |  | max_length=80; db_index=True
case_revision | models.PositiveIntegerField |  | 
routing_generation | models.PositiveIntegerField |  | 
status | models.CharField |  | max_length=16; choices=STATUS_CHOICES; db_index=True
recipient_snapshot | models.JSONField |  | blank=True
acted_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='acted_tat_tasks'
acted_at | models.DateTimeField |  | null=True; blank=True
superseded_by | models.ForeignKey | 'self' | null=True; blank=True; on_delete=models.SET_NULL; related_name='supersedes'
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-created_at']", "constraints": "[models.UniqueConstraint(fields=['case', 'stage_key', 'case_revision'], name='unique_tat_task_case_stage_revision')]", "indexes": "[models.Index(fields=['case', 'status', 'created_at']), models.Index(fields=['group_configuration', 'responsible_role', 'status'])]"}`

## core/models.py::TatActionTaskLocator

[[F:core/models.py#1556-1572#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
task | models.ForeignKey | TatActionTask | on_delete=models.CASCADE; related_name='locators'
recipient | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.CASCADE; related_name='tat_task_locators'
token_hash | models.CharField |  | max_length=64; unique=True; db_index=True
expires_at | models.DateTimeField |  | db_index=True
revoked_at | models.DateTimeField |  | null=True; blank=True; db_index=True
created_at | models.DateTimeField |  | 

Model metadata: `{"indexes": "[models.Index(fields=['task', 'recipient', 'expires_at'])]"}`

## core/models.py::TatActionTaskRecipient

[[F:core/models.py#1575-1626#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
task | models.ForeignKey | TatActionTask | on_delete=models.CASCADE; related_name='recipients'
user | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.CASCADE; related_name='tat_action_task_recipients'
kind | models.CharField |  | max_length=16; choices=KIND_CHOICES
rank | models.PositiveSmallIntegerField |  | 
threshold_percent | models.PositiveSmallIntegerField |  | null=True; blank=True
routing_generation | models.PositiveIntegerField |  | 
inbox_status | models.CharField |  | max_length=16; choices=INBOX_CHOICES; db_index=True
delivery_state | models.CharField |  | max_length=16; choices=DELIVERY_CHOICES; db_index=True
deliver_after | models.DateTimeField |  | null=True; blank=True; db_index=True
delivery_attempts | models.PositiveSmallIntegerField |  | 
telegram_message_id | models.CharField |  | max_length=100; blank=True
delivery_error | models.CharField |  | max_length=500; blank=True
delivered_at | models.DateTimeField |  | null=True; blank=True
read_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['task', 'rank', 'created_at']", "constraints": "[models.UniqueConstraint(fields=['task', 'user'], name='unique_tat_task_recipient')]", "indexes": "[models.Index(fields=['user', 'inbox_status', 'created_at'])]"}`

## core/models.py::TatTaskRerouteEvent

[[F:core/models.py#1629-1658#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
task | models.ForeignKey | TatActionTask | on_delete=models.CASCADE; related_name='reroute_events'
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='tat_task_reroute_events'
request_id | models.CharField |  | max_length=128; db_index=True
reason | models.TextField |  | 
generation_before | models.PositiveIntegerField |  | 
generation_after | models.PositiveIntegerField |  | 
before_snapshot | models.JSONField |  | 
after_snapshot | models.JSONField |  | 
created_at | models.DateTimeField |  | db_index=True

Model metadata: `{"ordering": "['-created_at']", "constraints": "[models.UniqueConstraint(fields=['task', 'request_id'], name='unique_tat_task_reroute_request')]"}`

## core/models.py::TatResponsibilityChangePlan

[[F:core/models.py#1661-1694#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
assignment | models.ForeignKey | TatResponsibilityAssignment | on_delete=models.PROTECT; related_name='change_plans'
proposed_snapshot | models.JSONField |  | 
expected_updated_at | models.DateTimeField |  | 
effective_at | models.DateTimeField |  | db_index=True
status | models.CharField |  | max_length=16; choices=STATUS_CHOICES; db_index=True
reason | models.TextField |  | 
request_id | models.CharField |  | max_length=128; unique=True
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='created_tat_responsibility_change_plans'
created_at | models.DateTimeField |  | 
applied_at | models.DateTimeField |  | null=True; blank=True
error | models.CharField |  | max_length=500; blank=True

Model metadata: `{"ordering": "['-created_at']"}`

## core/models.py::TatConfigurationEvent

[[F:core/models.py#1697-1730#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
group_configuration | models.ForeignKey | 'GroupSheetConfiguration' | null=True; blank=True; on_delete=models.SET_NULL; related_name='tat_configuration_events'
action | models.CharField |  | max_length=80; db_index=True
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='tat_configuration_events'
request_id | models.CharField |  | max_length=128; blank=True; db_index=True
reason | models.TextField |  | blank=True
before_snapshot | models.JSONField |  | blank=True
after_snapshot | models.JSONField |  | blank=True
metadata | models.JSONField |  | blank=True
created_at | models.DateTimeField |  | db_index=True

Model metadata: `{"ordering": "['-created_at']", "constraints": "[models.UniqueConstraint(fields=['action', 'request_id'], condition=~models.Q(request_id=''), name='unique_tat_configuration_event_request')]"}`

## core/models.py::TatPresentationSettings

[[F:core/models.py#1733-1764#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
singleton | models.PositiveSmallIntegerField |  | primary_key=True
business_time_enabled | models.BooleanField |  | 
near_target_percent | models.PositiveSmallIntegerField |  | 
report_panel_order | models.JSONField |  | blank=True
revision | models.PositiveIntegerField |  | 
change_reason | models.TextField |  | blank=True
updated_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='updated_tat_presentation_settings'
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"constraints": "[models.CheckConstraint(condition=models.Q(singleton=1), name='tat_presentation_singleton_one'), models.CheckConstraint(condition=models.Q(near_target_percent__gte=50, near_target_percent__lte=99), name='tat_presentation_near_target_range')]"}`

## core/models.py::TatGroupExceptionStatus

[[F:core/models.py#1767-1791#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
group_configuration | models.ForeignKey | 'GroupSheetConfiguration' | on_delete=models.CASCADE; related_name='tat_group_exception_statuses'
responsible_role | models.CharField |  | max_length=80
telegram_message_id | models.CharField |  | max_length=100; blank=True
unresolved_count | models.PositiveIntegerField |  | 
oldest_task_at | models.DateTimeField |  | null=True; blank=True
last_attempt_at | models.DateTimeField |  | null=True; blank=True
last_error | models.CharField |  | max_length=500; blank=True
active | models.BooleanField |  | db_index=True
updated_at | models.DateTimeField |  | 

Model metadata: `{"constraints": "[models.UniqueConstraint(fields=['group_configuration', 'responsible_role'], name='unique_tat_group_role_exception')]"}`

## core/models.py::TatNotificationProcessorRun

[[F:core/models.py#1794-1849#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
status | models.CharField |  | max_length=24; choices=STATUS_CHOICES; db_index=True
active_lock_key | models.CharField |  | max_length=64; null=True; blank=True; unique=True
started_at | models.DateTimeField |  | db_index=True
completed_at | models.DateTimeField |  | null=True; blank=True; db_index=True
processed_task_count | models.PositiveIntegerField |  | 
processed_dispatch_count | models.PositiveIntegerField |  | 
dispatch_attention_count | models.PositiveIntegerField |  | 
retry_recipient_count | models.PositiveIntegerField |  | 
overdue_recipient_count | models.PositiveIntegerField |  | 
unreachable_recipient_count | models.PositiveIntegerField |  | 
error_code | models.CharField |  | max_length=80; blank=True
error_message | models.CharField |  | max_length=500; blank=True
trigger_source | models.CharField |  | max_length=16; choices=TRIGGER_CHOICES; db_index=True
triggered_by_id_snapshot | models.CharField |  | max_length=64; blank=True
triggered_by_username_snapshot | models.CharField |  | max_length=150; blank=True
trigger_reason | models.CharField |  | max_length=500; blank=True
request_id | models.CharField |  | max_length=128; blank=True; db_index=True

Model metadata: `{"ordering": "['-started_at']", "indexes": "[models.Index(fields=['status', 'started_at'], name='tat_notify_run_status_idx')]", "constraints": "[models.UniqueConstraint(fields=['request_id'], condition=~models.Q(request_id=''), name='unique_tat_notify_run_request')]"}`

## core/models.py::TatUpdateSideEffectDispatch

[[F:core/models.py#1852-1916#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
case | models.ForeignKey | TatTrackerCase | on_delete=models.PROTECT; related_name='update_dispatches'
workflow_revision | models.PositiveIntegerField |  | 
request_id | models.CharField |  | max_length=128; blank=True; db_index=True
effect_type | models.CharField |  | max_length=32; choices=EFFECT_CHOICES; db_index=True
status | models.CharField |  | max_length=24; choices=STATUS_CHOICES; db_index=True
cycle_attempts | models.PositiveSmallIntegerField |  | 
total_attempts | models.PositiveIntegerField |  | 
next_retry_at | models.DateTimeField |  | null=True; blank=True; db_index=True
lease_token | models.UUIDField |  | null=True; blank=True
lease_started_at | models.DateTimeField |  | null=True; blank=True
last_error_code | models.CharField |  | max_length=80; blank=True
last_error_message | models.CharField |  | max_length=255; blank=True
manual_retry_reason | models.CharField |  | max_length=500; blank=True
manual_retry_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='retried_tat_update_dispatches'
completed_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | db_index=True
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['created_at', 'effect_type']", "constraints": "[models.UniqueConstraint(fields=['case', 'workflow_revision', 'effect_type'], name='unique_tat_update_effect_per_revision')]", "indexes": "[models.Index(fields=['status', 'next_retry_at'], name='tat_update_dispatch_due_idx'), models.Index(fields=['case', 'workflow_revision'], name='tat_update_dispatch_case_idx')]"}`

## core/models.py::TatRepairJob

[[F:core/models.py#1919-1968#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
group_configuration | models.ForeignKey | 'GroupSheetConfiguration' | on_delete=models.CASCADE; related_name='tat_repair_jobs'
product_key | models.CharField |  | max_length=80; blank=True; db_index=True
product | models.ForeignKey | 'Product' | null=True; blank=True; on_delete=models.PROTECT; related_name='tat_repair_jobs'
case_ids | models.JSONField |  | blank=True
cursor | models.PositiveIntegerField |  | 
total_cases | models.PositiveIntegerField |  | 
synced_cases | models.PositiveIntegerField |  | 
skipped_unlinked | models.PositiveIntegerField |  | 
failures | models.JSONField |  | blank=True
status | models.CharField |  | max_length=32; choices=STATUS_CHOICES; db_index=True
worker_token | models.UUIDField |  | null=True; blank=True
heartbeat_at | models.DateTimeField |  | null=True; blank=True; db_index=True
error | models.TextField |  | blank=True
requested_by | models.CharField |  | max_length=255; blank=True
started_at | models.DateTimeField |  | null=True; blank=True
completed_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-created_at']", "indexes": "[models.Index(fields=['status', 'updated_at']), models.Index(fields=['status', 'created_at'], name='tat_repair_status_created_idx')]"}`

## core/models.py::DurableJobRunnerHeartbeat

[[F:core/models.py#1971-1997#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
runner_key | models.CharField |  | max_length=80; primary_key=True
status | models.CharField |  | max_length=16; choices=STATUS_CHOICES
heartbeat_at | models.DateTimeField |  | db_index=True
last_started_at | models.DateTimeField |  | 
last_completed_at | models.DateTimeField |  | null=True; blank=True; db_index=True
processed_count | models.PositiveIntegerField |  | 
last_error_code | models.CharField |  | max_length=80; blank=True
updated_at | models.DateTimeField |  | 

Model metadata: `{}`

## core/models.py::TatCaseSequence

[[F:core/models.py#2000-2018#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
group_id | models.CharField |  | max_length=100; db_index=True
product_key | models.CharField |  | max_length=80; db_index=True
year | models.PositiveIntegerField |  | db_index=True
next_number | models.PositiveIntegerField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"constraints": "[models.UniqueConstraint(fields=['group_id', 'product_key', 'year'], name='unique_tat_sequence_group_product_year')]"}`

## core/models.py::WorkflowDataModeState

[[F:core/models.py#2021-2059#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.PositiveSmallIntegerField |  | primary_key=True
spin_mode | models.CharField |  | max_length=16; choices=WORKFLOW_DATA_MODE_CHOICES
spin_pilot_cycle_id | models.UUIDField |  | 
spin_mode_version | models.PositiveIntegerField |  | 
tat_mode | models.CharField |  | max_length=16; choices=WORKFLOW_DATA_MODE_CHOICES
tat_pilot_cycle_id | models.UUIDField |  | 
tat_mode_version | models.PositiveIntegerField |  | 
active_spin_purge_id | models.UUIDField |  | null=True; blank=True
active_tat_purge_id | models.UUIDField |  | null=True; blank=True
updated_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='workflow_data_mode_updates'
updated_at | models.DateTimeField |  | 

Model metadata: `{}`

## core/models.py::WorkflowDataModeEvent

[[F:core/models.py#2062-2110#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
workflow | models.CharField |  | max_length=32; choices=WORKFLOW_CHOICES; db_index=True
action | models.CharField |  | max_length=32; choices=ACTION_CHOICES; db_index=True
old_mode | models.CharField |  | max_length=16; choices=WORKFLOW_DATA_MODE_CHOICES; blank=True
new_mode | models.CharField |  | max_length=16; choices=WORKFLOW_DATA_MODE_CHOICES; blank=True
old_cycle_id | models.UUIDField |  | null=True; blank=True
new_cycle_id | models.UUIDField |  | null=True; blank=True
reason | models.TextField |  | 
request_id | models.CharField |  | max_length=128; blank=True; db_index=True
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='workflow_data_mode_events'
metadata | models.JSONField |  | blank=True
created_at | models.DateTimeField |  | db_index=True

Model metadata: `{"ordering": "['-created_at']", "constraints": "[models.UniqueConstraint(fields=['workflow', 'action', 'request_id'], condition=~models.Q(request_id=''), name='unique_workflow_mode_event_request')]"}`

## core/models.py::WorkflowPilotFormulaReadiness

[[F:core/models.py#2113-2147#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
workflow | models.CharField |  | max_length=32; choices=WORKFLOW_CHOICES; db_index=True
group_configuration | models.ForeignKey | 'GroupSheetConfiguration' | null=True; blank=True; on_delete=models.PROTECT; related_name='workflow_pilot_formula_readiness'
sheet_id | models.CharField |  | max_length=255; db_index=True
sheet_tab | models.CharField |  | max_length=255
configuration_fingerprint | models.CharField |  | max_length=64
formula_fingerprint | models.CharField |  | max_length=64
note | models.TextField |  | 
acknowledged_by | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='acknowledged_workflow_pilot_formula_readiness'
acknowledged_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['workflow', 'sheet_tab', '-acknowledged_at']", "constraints": "[models.UniqueConstraint(fields=['workflow', 'sheet_id', 'sheet_tab', 'configuration_fingerprint', 'formula_fingerprint'], name='unique_workflow_pilot_formula_readiness')]"}`

## core/models.py::WorkflowPilotPurgeRun

[[F:core/models.py#2150-2195#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
scope | models.CharField |  | max_length=32; choices=SCOPE_CHOICES; db_index=True
status | models.CharField |  | max_length=16; choices=STATUS_CHOICES; db_index=True
reason | models.TextField |  | 
request_id | models.CharField |  | max_length=128; blank=True; db_index=True
manifest | models.JSONField |  | blank=True
manifest_hash | models.CharField |  | max_length=64; blank=True; db_index=True
progress | models.JSONField |  | blank=True
failures | models.JSONField |  | blank=True
cutoff_at | models.DateTimeField |  | 
requested_by | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='requested_workflow_pilot_purges'
started_at | models.DateTimeField |  | null=True; blank=True
heartbeat_at | models.DateTimeField |  | null=True; blank=True; db_index=True
completed_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-created_at']", "constraints": "[models.UniqueConstraint(fields=['scope', 'request_id'], condition=~models.Q(request_id=''), name='unique_workflow_pilot_purge_request')]", "indexes": "[models.Index(fields=['scope', 'status', 'created_at'])]"}`

## core/models.py::LiveSheetRecordChange

[[F:core/models.py#2198-2243#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
group_configuration | models.ForeignKey | 'GroupSheetConfiguration' | on_delete=models.SET_NULL; null=True; blank=True; related_name='live_sheet_changes'
group_id | models.CharField |  | max_length=100; db_index=True
sheet_id | models.CharField |  | max_length=255; blank=True; db_index=True
sheet_tab | models.CharField |  | max_length=255; blank=True
row_number | models.PositiveIntegerField |  | 
record_key | models.CharField |  | max_length=255; blank=True; db_index=True
action | models.CharField |  | max_length=20; choices=ACTION_CHOICES
changed_by | models.CharField |  | max_length=255; blank=True
changes | models.JSONField |  | blank=True
status | models.CharField |  | max_length=20; choices=STATUS_CHOICES
error | models.TextField |  | blank=True
created_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-created_at']", "indexes": "[models.Index(fields=['group_id', 'created_at']), models.Index(fields=['sheet_id', 'sheet_tab'])]"}`

## core/models.py::JawabuVisitRecord

[[F:core/models.py#2246-2309#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
group_id | models.CharField |  | max_length=100; db_index=True
sheet_id | models.CharField |  | max_length=255; blank=True; db_index=True
sheet_tab | models.CharField |  | max_length=255; blank=True
row_number | models.PositiveIntegerField |  | null=True; blank=True
telegram_message_id | models.CharField |  | max_length=255; blank=True; db_index=True
source_telegram_message_id | models.CharField |  | max_length=255; blank=True; db_index=True
whatsapp_message_index | models.PositiveIntegerField |  | null=True; blank=True
whatsapp_message_at | models.DateTimeField |  | null=True; blank=True
sender | models.CharField |  | max_length=255; blank=True
national_id | models.CharField |  | max_length=64; blank=True; db_index=True
primary_phone | models.CharField |  | max_length=32; blank=True; db_index=True
duplicate_key | models.CharField |  | max_length=128; blank=True; db_index=True
duplicate_group_id | models.CharField |  | max_length=128; blank=True; db_index=True
duplicate_status | models.CharField |  | max_length=32; choices=DUPLICATE_STATUS_CHOICES
import_status | models.CharField |  | max_length=32; choices=IMPORT_STATUS_CHOICES
parsed_fields | models.JSONField |  | blank=True
raw_text | models.TextField |  | blank=True
sync_error | models.TextField |  | blank=True
review_notes | models.TextField |  | blank=True
created_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-created_at']", "indexes": "[models.Index(fields=['group_id', 'created_at']), models.Index(fields=['group_id', 'duplicate_key']), models.Index(fields=['national_id', 'primary_phone']), models.Index(fields=['import_status', 'duplicate_status'])]"}`

## core/models.py::JawabuCustomer

[[F:core/models.py#2312-2331#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
national_id | models.CharField |  | max_length=64; blank=True; db_index=True
primary_phone | models.CharField |  | max_length=32; blank=True; db_index=True
customer_no | models.CharField |  | max_length=64; blank=True; db_index=True
identity_enforced | models.BooleanField |  | db_index=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"constraints": "[models.UniqueConstraint(fields=['national_id'], condition=models.Q(identity_enforced=True) & ~models.Q(national_id=''), name='jawabu_customer_unique_national_id'), models.UniqueConstraint(fields=['primary_phone'], condition=models.Q(identity_enforced=True) & ~models.Q(primary_phone=''), name='jawabu_customer_unique_primary_phone'), models.UniqueConstraint(fields=['customer_no'], condition=models.Q(identity_enforced=True) & ~models.Q(customer_no=''), name='jawabu_customer_unique_customer_no')]"}`

## core/models.py::JawabuCustomerPhoneHistory

[[F:core/models.py#2334-2361#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
customer | models.ForeignKey | JawabuCustomer | on_delete=models.CASCADE; related_name='phone_history'
phone | models.CharField |  | max_length=32; db_index=True
source | models.CharField |  | max_length=40; blank=True; db_index=True
is_current | models.BooleanField |  | db_index=True
first_seen_at | models.DateTimeField |  | 
last_seen_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-last_seen_at']", "constraints": "[models.UniqueConstraint(fields=['customer', 'phone'], name='jawabu_unique_customer_phone_history')]", "indexes": "[models.Index(fields=['phone', 'is_current'])]"}`

## core/models.py::JawabuFarmerMaster

[[F:core/models.py#2364-2669#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
group_configuration | models.ForeignKey | 'GroupSheetConfiguration' | null=True; blank=True; on_delete=models.PROTECT; related_name='portal_cases'
case_reference_number | models.PositiveBigIntegerField |  | unique=True
customer | models.ForeignKey | JawabuCustomer | on_delete=models.PROTECT; null=True; blank=True; related_name='applications'
unit_number | models.PositiveIntegerField |  | 
source | models.CharField |  | max_length=100; db_index=True
source_name | models.CharField |  | max_length=255; blank=True
source_row_number | models.PositiveIntegerField |  | null=True; blank=True
source_fingerprint | models.CharField |  | max_length=64; blank=True; db_index=True
external_id | models.CharField |  | max_length=128; blank=True; db_index=True
customer_name | models.CharField |  | max_length=255; blank=True; db_index=True
national_id | models.CharField |  | max_length=64; blank=True; db_index=True
primary_phone | models.CharField |  | max_length=32; blank=True; db_index=True
secondary_phone | models.CharField |  | max_length=32; blank=True
lead_name | models.CharField |  | max_length=255; blank=True
lead_national_id | models.CharField |  | max_length=64; blank=True
lead_primary_phone | models.CharField |  | max_length=32; blank=True
lead_secondary_phone | models.CharField |  | max_length=32; blank=True
lead_source_reference | models.CharField |  | max_length=255; blank=True
county | models.CharField |  | max_length=128; blank=True; db_index=True
sub_county | models.CharField |  | max_length=128; blank=True
ward | models.CharField |  | max_length=128; blank=True
village | models.CharField |  | max_length=255; blank=True
landmark | models.TextField |  | blank=True
branch | models.CharField |  | max_length=128; blank=True; db_index=True
branch_ref | models.ForeignKey | 'OperationalLocation' | null=True; blank=True; on_delete=models.PROTECT; related_name='jawabu_branch_records'
county_ref | models.ForeignKey | 'OperationalLocation' | null=True; blank=True; on_delete=models.PROTECT; related_name='jawabu_county_records'
sub_county_ref | models.ForeignKey | 'OperationalLocation' | null=True; blank=True; on_delete=models.PROTECT; related_name='jawabu_sub_county_records'
hbg_contract_name | models.CharField |  | max_length=128; blank=True; db_index=True
lead_source | models.CharField |  | max_length=128; blank=True; db_index=True
contract_type | models.CharField |  | max_length=128; blank=True
installation_status | models.CharField |  | max_length=128; blank=True; db_index=True
actual_receipts_currency | models.CharField |  | max_length=16; blank=True
actual_receipts | models.CharField |  | max_length=64; blank=True
deposit_paid_hbg | models.DecimalField |  | max_digits=12; decimal_places=2; null=True; blank=True
hb_sales_person | models.CharField |  | max_length=255; blank=True; db_index=True
sign_date | models.CharField |  | max_length=32; blank=True
hbg_visit_date | models.DateField |  | null=True; blank=True; db_index=True
created_date | models.CharField |  | max_length=32; blank=True
comments | models.TextField |  | blank=True
gps_link | models.URLField |  | max_length=1000; blank=True
latitude | models.CharField |  | max_length=64; blank=True
longitude | models.CharField |  | max_length=64; blank=True
latitude_value | models.DecimalField |  | max_digits=9; decimal_places=6; null=True; blank=True
longitude_value | models.DecimalField |  | max_digits=9; decimal_places=6; null=True; blank=True
jbl_visit_date | models.DateField |  | null=True; blank=True; db_index=True
jbl_officer | models.CharField |  | max_length=255; blank=True
jbl_visit_status | models.CharField |  | max_length=80; blank=True; choices=JBL_VISIT_STATUS_CHOICES; db_index=True
jbl_visit_comment | models.TextField |  | blank=True
credit_decision | models.CharField |  | max_length=80; blank=True; choices=CREDIT_DECISION_CHOICES; db_index=True
credit_decided_by | models.CharField |  | max_length=255; blank=True
credit_decided_at | models.DateTimeField |  | null=True; blank=True
imab_created | models.CharField |  | max_length=32; blank=True
customer_no | models.CharField |  | max_length=64; blank=True; db_index=True
imab_customer_name | models.CharField |  | max_length=255; blank=True
system_branch | models.CharField |  | max_length=128; blank=True; db_index=True
system_loan_officer | models.CharField |  | max_length=255; blank=True
system_deposit_paid_jbl | models.DecimalField |  | max_digits=12; decimal_places=2; null=True; blank=True
repayment_date | models.CharField |  | max_length=64; blank=True
repayment_day | models.PositiveSmallIntegerField |  | null=True; blank=True
repayment_tenor | models.CharField |  | max_length=64; blank=True
repayment_tenor_months | models.PositiveSmallIntegerField |  | null=True; blank=True
payment_product | models.CharField |  | max_length=128; blank=True
product | models.ForeignKey | 'Product' | null=True; blank=True; on_delete=models.PROTECT; related_name='jawabu_farmer_records'
product_version | models.ForeignKey | 'ProductVersion' | null=True; blank=True; on_delete=models.PROTECT; related_name='jawabu_farmer_records'
product_terms_snapshot | models.JSONField |  | blank=True
product_quote_snapshot | models.JSONField |  | blank=True
product_requirement_evidence | models.JSONField |  | blank=True
product_custom_values | models.JSONField |  | blank=True
product_selected_fee_keys | models.JSONField |  | blank=True
final_decision | models.CharField |  | max_length=80; blank=True; choices=FINAL_DECISION_CHOICES; db_index=True
final_decision_comment | models.TextField |  | blank=True
final_decided_by | models.CharField |  | max_length=255; blank=True
final_decided_at | models.DateTimeField |  | null=True; blank=True
deferred_at | models.DateTimeField |  | null=True; blank=True; db_index=True
deferred_stage | models.CharField |  | max_length=32; blank=True; db_index=True
deferred_until | models.DateField |  | null=True; blank=True; db_index=True
workflow_state | models.CharField |  | max_length=40; blank=True; db_index=True
workflow_state_entered_at | models.DateTimeField |  | null=True; blank=True
workflow_revision | models.PositiveIntegerField |  | 
jbl_media_urls | models.TextField |  | blank=True
requisition_date | models.DateField |  | null=True; blank=True
order_number | models.CharField |  | max_length=128; blank=True; db_index=True
requisition_batch | models.ForeignKey | 'RequisitionBatch' | null=True; blank=True; on_delete=models.PROTECT; related_name='assigned_cases'
invoice_number | models.CharField |  | max_length=128; blank=True
invoice_date | models.DateField |  | null=True; blank=True
invoice_amount | models.DecimalField |  | max_digits=12; decimal_places=2; null=True; blank=True
discount | models.DecimalField |  | max_digits=12; decimal_places=2; null=True; blank=True
payment | models.DecimalField |  | max_digits=12; decimal_places=2; null=True; blank=True
balance_due | models.DecimalField |  | max_digits=12; decimal_places=2; null=True; blank=True
duplicate_key | models.CharField |  | max_length=255; blank=True; db_index=True
status | models.CharField |  | max_length=32; choices=STATUS_CHOICES; db_index=True
cleaning_notes | models.TextField |  | blank=True
raw_data | models.JSONField |  | blank=True
last_imported_at | models.DateTimeField |  | 
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['customer_name', 'national_id', 'primary_phone']", "indexes": "[models.Index(fields=['national_id', 'primary_phone']), models.Index(fields=['customer_name', 'county']), models.Index(fields=['status', 'updated_at']), models.Index(fields=['source', 'source_fingerprint']), models.Index(fields=['customer', 'unit_number']), models.Index(fields=['deferred_until', 'status'])]", "constraints": "[models.UniqueConstraint(fields=['customer', 'unit_number'], condition=models.Q(customer__isnull=False), name='jawabu_unique_customer_unit')]"}`

## core/models.py::JawabuApprovalDelegation

[[F:core/models.py#2672-2732#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
delegate | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='jawabu_approval_delegations'
gate | models.CharField |  | max_length=32; choices=GATE_CHOICES; db_index=True
source_role | models.CharField |  | max_length=80
branch | models.CharField |  | max_length=128; blank=True; db_index=True
product | models.CharField |  | max_length=128; blank=True; db_index=True
product_ref | models.ForeignKey | 'Product' | null=True; blank=True; on_delete=models.PROTECT; related_name='jawabu_approval_delegations'
reason | models.TextField |  | 
authorized_by | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='authorized_jawabu_approval_delegations'
starts_at | models.DateTimeField |  | db_index=True
expires_at | models.DateTimeField |  | db_index=True
revoked_at | models.DateTimeField |  | null=True; blank=True
revoked_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='revoked_jawabu_approval_delegations'
revocation_reason | models.TextField |  | blank=True
created_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-starts_at']", "indexes": "[models.Index(fields=['delegate', 'gate', 'expires_at'])]"}`

## core/models.py::JawabuApprovalDelegationEvent

[[F:core/models.py#2735-2752#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
delegation | models.ForeignKey | JawabuApprovalDelegation | on_delete=models.CASCADE; related_name='events'
action | models.CharField |  | max_length=24; choices=ACTION_CHOICES
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
note | models.TextField |  | blank=True
created_at | models.DateTimeField |  | db_index=True

Model metadata: `{"ordering": "['-created_at']"}`

## core/models.py::JawabuApprovalRecord

[[F:core/models.py#2755-2824#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
farmer | models.ForeignKey | JawabuFarmerMaster | on_delete=models.PROTECT; related_name='approval_records'
payment_document | models.ForeignKey | 'PaymentDocument' | null=True; blank=True; on_delete=models.PROTECT; related_name='case_approval_records'
gate | models.CharField |  | max_length=32; choices=GATE_CHOICES; db_index=True
decision | models.CharField |  | max_length=40; choices=DECISION_CHOICES
status | models.CharField |  | max_length=32; choices=STATUS_CHOICES; db_index=True
reason_code | models.CharField |  | max_length=64; blank=True
comment | models.TextField |  | blank=True
source_revision | models.PositiveIntegerField |  | 
authority_role | models.CharField |  | max_length=80; blank=True
delegation | models.ForeignKey | JawabuApprovalDelegation | null=True; blank=True; on_delete=models.PROTECT; related_name='approval_records'
decided_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
decided_by_label | models.CharField |  | max_length=255; blank=True
decided_at | models.DateTimeField |  | db_index=True
expires_at | models.DateTimeField |  | null=True; blank=True; db_index=True
invalidated_at | models.DateTimeField |  | null=True; blank=True
invalidated_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
invalidation_reason | models.TextField |  | blank=True
created_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-decided_at', '-created_at']", "indexes": "[models.Index(fields=['farmer', 'gate', 'status']), models.Index(fields=['payment_document', 'gate', 'status'])]"}`

## core/models.py::JawabuApprovalCondition

[[F:core/models.py#2827-2845#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
approval | models.ForeignKey | JawabuApprovalRecord | on_delete=models.CASCADE; related_name='conditions'
description | models.CharField |  | max_length=500
satisfied_at | models.DateTimeField |  | null=True; blank=True
satisfied_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
satisfaction_note | models.TextField |  | blank=True
created_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['created_at']"}`

## core/models.py::JawabuMediaAccessEvent

[[F:core/models.py#2848-2865#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
farmer | models.ForeignKey | JawabuFarmerMaster | null=True; blank=True; on_delete=models.SET_NULL; related_name='media_access_events'
attachment | models.ForeignKey | MediaAttachment | null=True; blank=True; on_delete=models.SET_NULL; related_name='access_events'
farmer_id_snapshot | models.CharField |  | max_length=64; blank=True
attachment_id_snapshot | models.CharField |  | max_length=64; blank=True
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
action | models.CharField |  | max_length=32
request_id | models.CharField |  | max_length=128; blank=True; db_index=True
created_at | models.DateTimeField |  | db_index=True

Model metadata: `{"ordering": "['-created_at']", "indexes": "[models.Index(fields=['farmer', 'created_at'])]"}`

## core/models.py::JawabuPipelineEvent

[[F:core/models.py#2868-2911#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
farmer | models.ForeignKey | JawabuFarmerMaster | on_delete=models.PROTECT; related_name='pipeline_events'
action | models.CharField |  | max_length=40; db_index=True
stage_key | models.CharField |  | max_length=40; blank=True; db_index=True
actor | models.CharField |  | max_length=255; blank=True
actor_telegram_id | models.CharField |  | max_length=100; blank=True; db_index=True
actor_user | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='jawabu_pipeline_actions'
authority_user | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='jawabu_pipeline_authorized_actions'
source | models.CharField |  | max_length=40; blank=True; db_index=True
request_id | models.CharField |  | max_length=128; blank=True; db_index=True
transition_code | models.CharField |  | max_length=120; blank=True; db_index=True
from_state | models.CharField |  | max_length=120; blank=True; db_index=True
to_state | models.CharField |  | max_length=120; blank=True; db_index=True
reason | models.TextField |  | blank=True
revision_before | models.PositiveIntegerField |  | null=True; blank=True
revision_after | models.PositiveIntegerField |  | null=True; blank=True
old_values | models.JSONField |  | blank=True
new_values | models.JSONField |  | blank=True
metadata | models.JSONField |  | blank=True
occurred_at | models.DateTimeField |  | db_index=True
created_at | models.DateTimeField |  | db_index=True

Model metadata: `{"ordering": "['-created_at']", "indexes": "[models.Index(fields=['farmer', 'occurred_at'], name='jawabu_farmer_timeline_idx'), models.Index(fields=['farmer', 'stage_key'], name='jawabu_farmer_stage_idx')]", "constraints": "[models.UniqueConstraint(fields=['farmer', 'request_id'], condition=~models.Q(request_id=''), name='jawabu_unique_event_request')]"}`

## core/models.py::JawabuCaseComment

[[F:core/models.py#2914-2961#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
farmer | models.ForeignKey | JawabuFarmerMaster | on_delete=models.PROTECT; related_name='case_comments'
pipeline_event | models.ForeignKey | JawabuPipelineEvent | null=True; blank=True; on_delete=models.SET_NULL; related_name='case_comments'
stage_key | models.CharField |  | max_length=40; db_index=True
comment | models.TextField |  | 
actor | models.CharField |  | max_length=255; blank=True
actor_user | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='jawabu_case_comments'
role_code | models.CharField |  | max_length=64; blank=True
role_label | models.CharField |  | max_length=128; blank=True
request_id | models.CharField |  | max_length=128; blank=True; db_index=True
occurred_at | models.DateTimeField |  | db_index=True
created_at | models.DateTimeField |  | db_index=True

Model metadata: `{"ordering": "['occurred_at', 'created_at']", "indexes": "[models.Index(fields=['farmer', 'occurred_at'], name='jawabu_comment_timeline_idx')]", "constraints": "[models.CheckConstraint(condition=~models.Q(comment=''), name='jawabu_case_comment_not_empty'), models.UniqueConstraint(fields=['farmer', 'request_id'], condition=~models.Q(request_id=''), name='jawabu_unique_comment_request')]"}`

## core/models.py::PortalMaintenanceState

[[F:core/models.py#2964-2991#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
singleton | models.PositiveSmallIntegerField |  | unique=True
mode | models.CharField |  | max_length=16; choices=MODE_CHOICES; db_index=True
reason | models.CharField |  | max_length=500; blank=True
updated_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
updated_at | models.DateTimeField |  | 

Model metadata: `{"constraints": "[models.CheckConstraint(condition=models.Q(singleton=1), name='portal_maintenance_singleton_one')]"}`

## core/models.py::BusinessCalendarHoliday

[[F:core/models.py#2994-3009#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
date | models.DateField |  | unique=True; db_index=True
name | models.CharField |  | max_length=160
active | models.BooleanField |  | db_index=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['date']"}`

## core/models.py::WorkflowTimelineAnnotation

[[F:core/models.py#3012-3066#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
workflow | models.CharField |  | max_length=40; choices=WORKFLOW_CHOICES; db_index=True
subject_id | models.CharField |  | max_length=64; db_index=True
source_event_id | models.CharField |  | max_length=64; db_index=True
kind | models.CharField |  | max_length=20; choices=KIND_CHOICES; db_index=True
supersedes_event_id | models.CharField |  | max_length=64; blank=True; db_index=True
note | models.TextField |  | blank=True
artifact_name | models.CharField |  | max_length=255; blank=True
artifact_url | models.URLField |  | max_length=1000; blank=True
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='workflow_timeline_annotations'
authority_user | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='workflow_timeline_annotation_authorizations'
created_at | models.DateTimeField |  | db_index=True

Model metadata: `{"ordering": "['-created_at']", "indexes": "[models.Index(fields=['workflow', 'subject_id', 'created_at']), models.Index(fields=['workflow', 'source_event_id', 'kind'])]", "constraints": "[models.UniqueConstraint(fields=['workflow', 'subject_id', 'source_event_id', 'kind'], condition=models.Q(kind='redaction'), name='unique_workflow_timeline_redaction')]"}`

## core/models.py::WorkflowSlaEscalation

[[F:core/models.py#3069-3128#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
data_mode | models.CharField |  | max_length=16; choices=WORKFLOW_DATA_MODE_CHOICES; db_index=True
pilot_cycle_id | models.UUIDField |  | null=True; blank=True; db_index=True
data_scope_key | models.CharField |  | max_length=64; db_index=True
workflow | models.CharField |  | max_length=40; choices=WORKFLOW_CHOICES; db_index=True
subject_id | models.CharField |  | max_length=64; db_index=True
group_id | models.CharField |  | max_length=100; blank=True; db_index=True
stage_key | models.CharField |  | max_length=120; db_index=True
branch | models.CharField |  | max_length=128; blank=True; db_index=True
responsible_role | models.CharField |  | max_length=80; blank=True; db_index=True
responsible_actor | models.CharField |  | max_length=160; blank=True; db_index=True
target_minutes | models.PositiveIntegerField |  | 
overdue_minutes | models.PositiveIntegerField |  | 
escalation_level | models.PositiveSmallIntegerField |  | db_index=True
threshold_percent | models.PositiveSmallIntegerField |  | 
escalation_date | models.DateField |  | db_index=True
status | models.CharField |  | max_length=20; choices=STATUS_CHOICES; db_index=True
acknowledged_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='acknowledged_workflow_sla_escalations'
resolved_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='resolved_workflow_sla_escalations'
follow_up_note | models.TextField |  | blank=True
created_at | models.DateTimeField |  | 
acknowledged_at | models.DateTimeField |  | null=True; blank=True
resolved_at | models.DateTimeField |  | null=True; blank=True

Model metadata: `{"ordering": "['-created_at']", "constraints": "[models.UniqueConstraint(fields=['workflow', 'subject_id', 'stage_key', 'escalation_date', 'data_scope_key'], name='unique_workflow_sla_escalation_day')]", "indexes": "[models.Index(fields=['workflow', 'status', 'created_at']), models.Index(fields=['group_id', 'stage_key', 'status'])]"}`

## core/models.py::TatEscalationRule

[[F:core/models.py#3131-3165#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
group_configuration | models.ForeignKey | 'GroupSheetConfiguration' | on_delete=models.CASCADE; related_name='tat_escalation_rules'
threshold_percent | models.PositiveSmallIntegerField |  | 
routing_role | models.CharField |  | max_length=80; choices=ROUTING_CHOICES
branch | models.CharField |  | max_length=120; blank=True; db_index=True
active | models.BooleanField |  | db_index=True
approved_at | models.DateTimeField |  | db_index=True
approved_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='approved_tat_escalation_rules'
retired_at | models.DateTimeField |  | null=True; blank=True

Model metadata: `{"ordering": "['branch', 'threshold_percent', '-approved_at']", "constraints": "[models.UniqueConstraint(fields=['group_configuration', 'branch', 'threshold_percent'], condition=models.Q(active=True), name='unique_active_tat_escalation_rule')]"}`

## core/models.py::WorkflowTatDailyMetric

[[F:core/models.py#3168-3231#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
data_mode | models.CharField |  | max_length=16; choices=WORKFLOW_DATA_MODE_CHOICES; db_index=True
pilot_cycle_id | models.UUIDField |  | null=True; blank=True; db_index=True
data_scope_key | models.CharField |  | max_length=64; db_index=True
metric_grain | models.CharField |  | max_length=32; db_index=True
metric_date | models.DateField |  | db_index=True
workflow | models.CharField |  | max_length=40; choices=WORKFLOW_CHOICES; db_index=True
group_id | models.CharField |  | max_length=100; blank=True; db_index=True
branch | models.CharField |  | max_length=128; blank=True; db_index=True
product_key | models.CharField |  | max_length=80; blank=True; db_index=True
product | models.ForeignKey | 'Product' | null=True; blank=True; on_delete=models.PROTECT; related_name='tat_daily_metrics'
stage_key | models.CharField |  | max_length=120; db_index=True
responsible_role | models.CharField |  | max_length=80; blank=True; db_index=True
responsible_actor | models.CharField |  | max_length=160; blank=True; db_index=True
outcome | models.CharField |  | max_length=24; blank=True; db_index=True
active_count | models.PositiveIntegerField |  | 
completed_count | models.PositiveIntegerField |  | 
overdue_count | models.PositiveIntegerField |  | 
near_target_count | models.PositiveIntegerField |  | 
stalled_count | models.PositiveIntegerField |  | 
target_unavailable_count | models.PositiveIntegerField |  | 
created_count | models.PositiveIntegerField |  | 
finished_count | models.PositiveIntegerField |  | 
disbursed_count | models.PositiveIntegerField |  | 
rejected_count | models.PositiveIntegerField |  | 
declined_count | models.PositiveIntegerField |  | 
sla_met_count | models.PositiveIntegerField |  | 
near_target_percent | models.PositiveSmallIntegerField |  | 
presentation_revision | models.PositiveIntegerField |  | 
sample_count | models.PositiveIntegerField |  | 
median_sla_minutes | models.DecimalField |  | max_digits=14; decimal_places=2; null=True; blank=True
p90_sla_minutes | models.DecimalField |  | max_digits=14; decimal_places=2; null=True; blank=True
median_wall_clock_minutes | models.DecimalField |  | max_digits=14; decimal_places=2; null=True; blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-metric_date', 'workflow', 'stage_key']", "constraints": "[models.UniqueConstraint(fields=['metric_date', 'workflow', 'group_id', 'branch', 'product_key', 'stage_key', 'responsible_role', 'responsible_actor', 'outcome', 'metric_grain', 'data_scope_key'], name='unique_workflow_tat_daily_metric_v2')]", "indexes": "[models.Index(fields=['workflow', 'metric_date', 'branch']), models.Index(fields=['group_id', 'metric_date', 'stage_key'])]"}`

## core/models.py::WorkflowTatMetricRebuildRequest

[[F:core/models.py#3234-3270#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
case | models.ForeignKey | TatTrackerCase | null=True; blank=True; on_delete=models.CASCADE; related_name='metric_rebuild_requests'
request_key | models.CharField |  | max_length=160; unique=True
correction_revision | models.PositiveIntegerField |  | 
date_from | models.DateField |  | 
date_to | models.DateField |  | 
next_date | models.DateField |  | 
status | models.CharField |  | max_length=16; choices=STATUS_CHOICES; db_index=True
attempts | models.PositiveSmallIntegerField |  | 
last_error | models.CharField |  | max_length=500; blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 
completed_at | models.DateTimeField |  | null=True; blank=True

Model metadata: `{"ordering": "['created_at']", "constraints": "[models.UniqueConstraint(fields=['case', 'correction_revision'], name='unique_tat_metric_rebuild_revision')]", "indexes": "[models.Index(fields=['status', 'next_date'])]"}`

## core/models.py::JawabuDataQualityIssue

[[F:core/models.py#3273-3290#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
farmer | models.ForeignKey | JawabuFarmerMaster | on_delete=models.CASCADE; related_name='data_quality_issues'
field_name | models.CharField |  | max_length=80; db_index=True
code | models.CharField |  | max_length=80; db_index=True
severity | models.CharField |  | max_length=20; db_index=True
message | models.TextField |  | 
active | models.BooleanField |  | db_index=True
detected_at | models.DateTimeField |  | 
resolved_at | models.DateTimeField |  | null=True; blank=True

Model metadata: `{"ordering": "['field_name', 'code']", "constraints": "[models.UniqueConstraint(fields=['farmer', 'field_name', 'code'], name='jawabu_unique_quality_issue')]"}`

## core/models.py::JawabuDataQualityResolution

[[F:core/models.py#3293-3318#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
issue | models.ForeignKey | JawabuDataQualityIssue | on_delete=models.CASCADE; related_name='resolutions'
action | models.CharField |  | max_length=20; choices=ACTION_CHOICES; db_index=True
note | models.TextField |  | blank=True
actor | models.CharField |  | max_length=255; blank=True
before_value | models.TextField |  | blank=True
after_value | models.TextField |  | blank=True
created_at | models.DateTimeField |  | db_index=True

Model metadata: `{"ordering": "['-created_at']"}`

## core/models.py::JawabuCustomerFieldProvenance

[[F:core/models.py#3321-3344#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
farmer | models.ForeignKey | JawabuFarmerMaster | on_delete=models.CASCADE; related_name='field_provenance'
field_name | models.CharField |  | max_length=80; db_index=True
old_value | models.TextField |  | blank=True
new_value | models.TextField |  | blank=True
source | models.CharField |  | max_length=40; db_index=True
source_reference | models.CharField |  | max_length=255; blank=True
source_row_number | models.PositiveIntegerField |  | null=True; blank=True
actor | models.CharField |  | max_length=255; blank=True
occurred_at | models.DateTimeField |  | db_index=True

Model metadata: `{"ordering": "['-occurred_at']", "indexes": "[models.Index(fields=['farmer', 'field_name', 'occurred_at']), models.Index(fields=['source', 'occurred_at'])]"}`

## core/models.py::Product

[[F:core/models.py#3347-3392#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
name | models.CharField |  | max_length=128
code | models.CharField |  | max_length=64; blank=True
description | models.TextField |  | blank=True
category | models.CharField |  | max_length=64; blank=True; db_index=True
active | models.BooleanField |  | db_index=True
sort_order | models.PositiveIntegerField |  | 
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['sort_order', 'name']", "constraints": "[models.UniqueConstraint(Lower('name'), name='jawabu_unique_operational_product_name_ci'), models.UniqueConstraint(Lower('code'), condition=~models.Q(code=''), name='jawabu_unique_operational_product_code_ci')]"}`

## core/models.py::ProductAlias

[[F:core/models.py#3401-3425#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
product | models.ForeignKey | Product | on_delete=models.CASCADE; related_name='aliases'
alias | models.CharField |  | max_length=160
normalized_alias | models.CharField |  | max_length=160; unique=True; db_index=True
created_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['alias']"}`

## core/models.py::ProductVersion

[[F:core/models.py#3428-3573#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
product | models.ForeignKey | Product | on_delete=models.PROTECT; related_name='versions'
version | models.PositiveIntegerField |  | 
status | models.CharField |  | max_length=16; choices=STATUS_CHOICES; db_index=True
currency | models.CharField |  | max_length=3
min_amount | models.DecimalField |  | max_digits=14; decimal_places=2
max_amount | models.DecimalField |  | max_digits=14; decimal_places=2; null=True; blank=True
min_tenor | models.PositiveSmallIntegerField |  | 
max_tenor | models.PositiveSmallIntegerField |  | 
tenor_unit | models.CharField |  | max_length=12; choices=TENOR_UNIT_CHOICES
interest_method | models.CharField |  | max_length=16; choices=INTEREST_METHOD_CHOICES
interest_rate | models.DecimalField |  | max_digits=9; decimal_places=6
interest_rate_period | models.CharField |  | max_length=12; choices=RATE_PERIOD_CHOICES
repayment_frequency | models.CharField |  | max_length=16; choices=REPAYMENT_FREQUENCY_CHOICES
quote_amount_field_key | models.SlugField |  | max_length=80
quote_tenor_field_key | models.SlugField |  | max_length=80
effective_from | models.DateField |  | db_index=True
effective_to | models.DateField |  | null=True; blank=True; db_index=True
supersedes | models.ForeignKey | 'self' | null=True; blank=True; on_delete=models.PROTECT; related_name='superseded_by_versions'
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='created_product_versions'
published_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='published_product_versions'
published_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['product__sort_order', 'product__name', '-version']", "constraints": "[models.UniqueConstraint(fields=['product', 'version'], name='unique_global_product_version')]", "indexes": "[models.Index(fields=['product', 'status', 'effective_from'])]"}`

## core/models.py::ProductFee

[[F:core/models.py#3583-3650#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
product_version | models.ForeignKey | ProductVersion | on_delete=models.CASCADE; related_name='fees'
key | models.SlugField |  | max_length=80
label | models.CharField |  | max_length=160
fee_type | models.CharField |  | max_length=16; choices=TYPE_CHOICES
fixed_amount | models.DecimalField |  | max_digits=14; decimal_places=2; null=True; blank=True
percentage | models.DecimalField |  | max_digits=9; decimal_places=6; null=True; blank=True
calculation_basis | models.CharField |  | max_length=24; choices=BASIS_CHOICES
minimum_amount | models.DecimalField |  | max_digits=14; decimal_places=2; null=True; blank=True
maximum_amount | models.DecimalField |  | max_digits=14; decimal_places=2; null=True; blank=True
collection_mode | models.CharField |  | max_length=16; choices=COLLECTION_CHOICES
mandatory | models.BooleanField |  | 
position | models.PositiveSmallIntegerField |  | 

Model metadata: `{"ordering": "['position', 'id']", "constraints": "[models.UniqueConstraint(fields=['product_version', 'key'], name='unique_product_fee_key')]"}`

## core/models.py::ProductRequirement

[[F:core/models.py#3653-3693#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
product_version | models.ForeignKey | ProductVersion | on_delete=models.CASCADE; related_name='requirements'
key | models.SlugField |  | max_length=80
label | models.CharField |  | max_length=160
description | models.TextField |  | blank=True
requirement_type | models.CharField |  | max_length=20; choices=TYPE_CHOICES
workflow | models.CharField |  | max_length=40; blank=True; db_index=True
enforcement_stage | models.CharField |  | max_length=80; blank=True; db_index=True
required | models.BooleanField |  | 
validation_config | models.JSONField |  | blank=True
position | models.PositiveSmallIntegerField |  | 
active | models.BooleanField |  | 

Model metadata: `{"ordering": "['position', 'id']", "constraints": "[models.UniqueConstraint(fields=['product_version', 'key'], name='unique_product_requirement_key')]"}`

## core/models.py::ProductCustomAttribute

[[F:core/models.py#3696-3745#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
product_version | models.ForeignKey | ProductVersion | on_delete=models.CASCADE; related_name='custom_attributes'
key | models.SlugField |  | max_length=80
label | models.CharField |  | max_length=160
attribute_type | models.CharField |  | max_length=16; choices=TYPE_CHOICES
required | models.BooleanField |  | 
help_text | models.CharField |  | max_length=500; blank=True
options | models.JSONField |  | blank=True
validation_config | models.JSONField |  | blank=True
default_value | models.JSONField |  | null=True; blank=True
workflow_visibility | models.JSONField |  | blank=True
position | models.PositiveSmallIntegerField |  | 

Model metadata: `{"ordering": "['position', 'id']", "constraints": "[models.UniqueConstraint(fields=['product_version', 'key'], name='unique_product_attribute_key')]"}`

## core/models.py::ProductAvailability

[[F:core/models.py#3748-3777#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
product | models.ForeignKey | Product | on_delete=models.CASCADE; related_name='availability_assignments'
branch | models.ForeignKey | 'OperationalLocation' | null=True; blank=True; on_delete=models.PROTECT; related_name='product_availability_assignments'
workflow | models.CharField |  | max_length=40; blank=True; db_index=True
channel | models.CharField |  | max_length=16; choices=CHANNEL_CHOICES; blank=True; db_index=True
scope_signature | models.CharField |  | max_length=180
active | models.BooleanField |  | db_index=True
created_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['product__sort_order', 'product__name', 'workflow', 'channel']", "constraints": "[models.UniqueConstraint(fields=['product', 'scope_signature'], name='unique_product_availability_scope')]"}`

## core/models.py::ProductTatConfiguration

[[F:core/models.py#3780-3858#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
product_version | models.OneToOneField | ProductVersion | on_delete=models.CASCADE; related_name='tat_configuration'
sheet_name | models.CharField |  | max_length=160
case_prefix | models.CharField |  | max_length=32
remarks_col | models.PositiveSmallIntegerField |  | 
status_col | models.PositiveSmallIntegerField |  | 
tat_start_col | models.PositiveSmallIntegerField |  | 
stage_columns | models.JSONField |  | 
stages | models.JSONField |  | 
stage_tat_columns | models.JSONField |  | blank=True
requires_valuation | models.BooleanField |  | 
hocc_threshold | models.DecimalField |  | max_digits=14; decimal_places=2

Model metadata: `{}`

## core/models.py::ProductVersionEvent

[[F:core/models.py#3861-3880#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
product_version | models.ForeignKey | ProductVersion | on_delete=models.PROTECT; related_name='events'
action | models.CharField |  | max_length=40; db_index=True
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='+'
metadata | models.JSONField |  | blank=True
occurred_at | models.DateTimeField |  | db_index=True

Model metadata: `{"ordering": "['occurred_at', 'id']"}`

## core/models.py::ProductMappingIssue

[[F:core/models.py#3883-3905#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
raw_value | models.CharField |  | max_length=255
normalized_value | models.CharField |  | max_length=160; db_index=True
source_workflow | models.CharField |  | max_length=40; db_index=True
source_model | models.CharField |  | max_length=120; blank=True
source_record_id | models.CharField |  | max_length=120; blank=True
status | models.CharField |  | max_length=16; choices=STATUS_CHOICES; db_index=True
product | models.ForeignKey | Product | null=True; blank=True; on_delete=models.PROTECT; related_name='mapping_issues'
resolved_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='+'
resolved_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-created_at']", "constraints": "[models.UniqueConstraint(fields=['normalized_value', 'source_workflow', 'source_model', 'source_record_id'], condition=models.Q(status='open'), name='unique_open_product_mapping_issue')]"}`

## core/models.py::UserProfile

[[F:core/models.py#3908-3939#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
user | models.OneToOneField | settings.AUTH_USER_MODEL | on_delete=models.CASCADE; related_name='staff_profile'
telegram_id | models.CharField |  | max_length=100; blank=True; db_index=True
telegram_username | models.CharField |  | max_length=100; blank=True; db_index=True
phone_number | models.CharField |  | max_length=20; blank=True; db_index=True
signing_national_id | models.CharField |  | max_length=40; blank=True
signing_phone_number | models.CharField |  | max_length=20; blank=True
signing_email | models.EmailField |  | blank=True
telegram_metadata | models.JSONField |  | blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['user__first_name', 'user__last_name', 'telegram_id']", "constraints": "[models.UniqueConstraint(fields=['telegram_id'], condition=models.Q(telegram_id__gt=''), name='unique_bound_telegram_id'), models.UniqueConstraint(models.functions.Lower('telegram_username'), condition=models.Q(telegram_username__gt=''), name='unique_enrolled_telegram_username')]"}`

## core/models.py::UserMiniAppPreference

[[F:core/models.py#3942-3972#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
user | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.CASCADE; related_name='miniapp_preferences'
workflow | models.CharField |  | max_length=40; choices=WORKFLOW_CHOICES; db_index=True
default_screen | models.CharField |  | max_length=80; blank=True
default_filters | models.JSONField |  | blank=True
compact_cards | models.BooleanField |  | 
show_business_hours_time | models.BooleanField |  | 
alert_mode | models.CharField |  | max_length=16; choices=ALERT_CHOICES
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"constraints": "[models.UniqueConstraint(fields=['user', 'workflow'], name='unique_user_miniapp_preference')]", "ordering": "['workflow', 'user_id']"}`

## core/models.py::PortalSavedView

[[F:core/models.py#3975-4014#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
user | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.CASCADE; related_name='portal_saved_views'
name | models.CharField |  | max_length=60
screen | models.CharField |  | max_length=80
queue | models.CharField |  | max_length=80; blank=True
filters | models.JSONField |  | blank=True
ordering | models.CharField |  | max_length=24; choices=ORDERING_CHOICES
is_startup | models.BooleanField |  | 
last_used_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-is_startup', '-last_used_at', '-updated_at', 'name']", "constraints": "[models.UniqueConstraint(models.functions.Lower('name'), 'user', name='unique_portal_saved_view_name_per_user'), models.UniqueConstraint(fields=['user'], condition=models.Q(is_startup=True), name='unique_portal_saved_startup_view_per_user')]", "indexes": "[models.Index(fields=['user', 'is_startup'])]"}`

## core/models.py::PortalCaseWorkspace

[[F:core/models.py#4017-4046#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
user | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.CASCADE; related_name='portal_case_workspace_items'
farmer | models.ForeignKey | 'JawabuFarmerMaster' | on_delete=models.CASCADE; related_name='portal_workspace_items'
pinned | models.BooleanField |  | 
pinned_at | models.DateTimeField |  | null=True; blank=True
last_opened_at | models.DateTimeField |  | null=True; blank=True
recent_dismissed_at | models.DateTimeField |  | null=True; blank=True
unavailable_since | models.DateTimeField |  | null=True; blank=True
last_open_key | models.CharField |  | max_length=64; blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-pinned', '-pinned_at', '-last_opened_at']", "constraints": "[models.UniqueConstraint(fields=['user', 'farmer'], name='unique_portal_case_workspace_per_user')]", "indexes": "[models.Index(fields=['user', 'pinned', 'unavailable_since']), models.Index(fields=['user', 'last_opened_at'])]"}`

## core/models.py::PortalReportDefinition

[[F:core/models.py#4049-4098#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
title | models.CharField |  | max_length=100
source_key | models.CharField |  | max_length=40; choices=SOURCE_CHOICES
configuration | models.JSONField |  | blank=True
version | models.PositiveIntegerField |  | 
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='created_portal_report_definitions'
archived_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='archived_portal_report_definitions'
archived_at | models.DateTimeField |  | null=True; blank=True; db_index=True
is_active | models.BooleanField |  | db_index=True
create_request_id | models.CharField |  | max_length=128; blank=True; db_index=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-is_active', 'title']", "indexes": "[models.Index(fields=['is_active', 'title']), models.Index(fields=['created_by', 'created_at'])]", "constraints": "[models.UniqueConstraint(fields=['create_request_id'], condition=~models.Q(create_request_id=''), name='unique_portal_report_create_request')]"}`

## core/models.py::PortalReportChart

[[F:core/models.py#4101-4151#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
definition | models.ForeignKey | PortalReportDefinition | on_delete=models.CASCADE; related_name='charts'
title | models.CharField |  | max_length=100; blank=True
chart_type | models.CharField |  | max_length=16; choices=TYPE_CHOICES
dimension_field | models.CharField |  | max_length=80
metric_field | models.CharField |  | max_length=80; blank=True
aggregation | models.CharField |  | max_length=16; choices=AGGREGATE_CHOICES
date_bucket | models.CharField |  | max_length=12; choices=DATE_BUCKET_CHOICES; blank=True
position | models.PositiveSmallIntegerField |  | 
created_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['position', 'created_at']", "constraints": "[models.UniqueConstraint(fields=['definition', 'position'], name='unique_portal_report_chart_position')]"}`

## core/models.py::AccessGrant

[[F:core/models.py#4180-4284#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
user | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.CASCADE; related_name='access_grants'
workflow | models.CharField |  | max_length=40; choices=WORKFLOW_CHOICES; db_index=True
role | models.CharField |  | max_length=80; db_index=True
branch | models.CharField |  | max_length=120; blank=True; db_index=True
branch_ref | models.ForeignKey | 'OperationalLocation' | null=True; blank=True; on_delete=models.PROTECT; related_name='access_grants'
product | models.CharField |  | max_length=120; blank=True; db_index=True
product_ref | models.ForeignKey | 'Product' | null=True; blank=True; on_delete=models.PROTECT; related_name='access_grants'
group_configuration | models.ForeignKey | 'GroupSheetConfiguration' | on_delete=models.CASCADE; null=True; blank=True; related_name='user_access_grants'
active | models.BooleanField |  | db_index=True
source | models.CharField |  | max_length=40
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['workflow', 'role', 'branch', 'product']", "constraints": "[models.UniqueConstraint(fields=['user', 'workflow', 'role', 'branch', 'product', 'group_configuration'], condition=models.Q(group_configuration__isnull=False), name='unique_user_group_access_scope'), models.UniqueConstraint(fields=['user', 'workflow', 'role', 'branch', 'product'], condition=models.Q(group_configuration__isnull=True), name='unique_user_global_access_scope')]"}`

## core/models.py::WorkflowRoleCapability

[[F:core/models.py#4287-4350#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
workflow | models.CharField |  | max_length=40; choices=AccessGrant.WORKFLOW_CHOICES; db_index=True
role | models.CharField |  | max_length=80; db_index=True
capability_key | models.CharField |  | max_length=120; db_index=True
enabled | models.BooleanField |  | 
effect | models.CharField |  | max_length=12; choices=EFFECT_CHOICES
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['workflow', 'role', 'capability_key']", "constraints": "[models.UniqueConstraint(fields=['workflow', 'role', 'capability_key'], name='unique_workflow_role_capability')]"}`

## core/models.py::WorkflowRoleCapabilityAuditEvent

[[F:core/models.py#4353-4374#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
workflow | models.CharField |  | max_length=40; choices=AccessGrant.WORKFLOW_CHOICES; db_index=True
role | models.CharField |  | max_length=80; db_index=True
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
changes | models.JSONField |  | blank=True
source | models.CharField |  | max_length=40
created_at | models.DateTimeField |  | db_index=True

Model metadata: `{"ordering": "['-created_at']", "indexes": "[models.Index(fields=['workflow', 'role', 'created_at'])]"}`

## core/models.py::AccessControlPolicyState

[[F:core/models.py#4377-4386#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
singleton | models.PositiveSmallIntegerField |  | primary_key=True
version | models.PositiveIntegerField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{}`

## core/models.py::AccessControlCheckerAssignment

[[F:core/models.py#4389-4453#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
user | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='access_control_checker_assignments'
appointed_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='appointed_access_control_checkers'
appointment_reason | models.TextField |  | 
source | models.CharField |  | max_length=32; choices=SOURCE_CHOICES
appointed_at | models.DateTimeField |  | db_index=True
revoked_at | models.DateTimeField |  | null=True; blank=True; db_index=True
revoked_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='revoked_access_control_checkers'
revocation_reason | models.TextField |  | blank=True

Model metadata: `{"ordering": "['-appointed_at']", "constraints": "[models.UniqueConstraint(fields=['user'], condition=models.Q(revoked_at__isnull=True), name='unique_active_access_control_checker')]", "indexes": "[models.Index(fields=['user', 'revoked_at'])]"}`

## core/models.py::AccessControlChangeRequest

[[F:core/models.py#4456-4513#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
change_type | models.CharField |  | max_length=32; choices=TYPE_CHOICES; db_index=True
workflow | models.CharField |  | max_length=40; choices=AccessGrant.WORKFLOW_CHOICES; blank=True; db_index=True
role | models.CharField |  | max_length=80; blank=True; db_index=True
target_roles | models.JSONField |  | blank=True
request_key | models.CharField |  | max_length=128; blank=True; db_index=True
target_user | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='access_control_requests'
before_snapshot | models.JSONField |  | blank=True
proposed_snapshot | models.JSONField |  | blank=True
impact | models.JSONField |  | blank=True
reason | models.TextField |  | 
status | models.CharField |  | max_length=16; choices=STATUS_CHOICES; db_index=True
policy_version | models.PositiveIntegerField |  | 
requested_by | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='requested_access_control_changes'
requested_at | models.DateTimeField |  | db_index=True
reviewed_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='reviewed_access_control_changes'
reviewed_at | models.DateTimeField |  | null=True; blank=True
review_comment | models.TextField |  | blank=True
applied_at | models.DateTimeField |  | null=True; blank=True
source_request | models.ForeignKey | 'self' | null=True; blank=True; on_delete=models.SET_NULL; related_name='derived_requests'

Model metadata: `{"ordering": "['-requested_at']", "indexes": "[models.Index(fields=['status', 'requested_at']), models.Index(fields=['workflow', 'role', 'status'])]", "constraints": "[models.UniqueConstraint(fields=['requested_by', 'request_key'], condition=~models.Q(request_key=''), name='unique_access_change_request_key')]"}`

## core/models.py::WorkflowConfigurationChangeRequest

[[F:core/models.py#4516-4568#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
workflow | models.CharField |  | max_length=40; choices=WORKFLOW_CHOICES; db_index=True
setting_key | models.CharField |  | max_length=40; choices=SETTING_CHOICES; db_index=True
group_configuration | models.ForeignKey | 'GroupSheetConfiguration' | null=True; blank=True; on_delete=models.PROTECT; related_name='workflow_configuration_requests'
before_snapshot | models.JSONField |  | blank=True
proposed_snapshot | models.JSONField |  | blank=True
reason | models.TextField |  | 
status | models.CharField |  | max_length=16; choices=STATUS_CHOICES; db_index=True
requested_by | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='requested_workflow_configuration_changes'
requested_at | models.DateTimeField |  | db_index=True
reviewed_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='reviewed_workflow_configuration_changes'
reviewed_at | models.DateTimeField |  | null=True; blank=True
review_comment | models.TextField |  | blank=True
request_id | models.CharField |  | max_length=128; blank=True; db_index=True
applied_at | models.DateTimeField |  | null=True; blank=True

Model metadata: `{"ordering": "['-requested_at']", "indexes": "[models.Index(fields=['workflow', 'setting_key', 'status', 'requested_at'])]", "constraints": "[models.UniqueConstraint(fields=['requested_by', 'request_id'], condition=~models.Q(request_id=''), name='unique_workflow_config_request_id')]"}`

## core/models.py::AccessControlPolicySnapshot

[[F:core/models.py#4571-4581#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
version | models.PositiveIntegerField |  | unique=True
request | models.OneToOneField | AccessControlChangeRequest | null=True; blank=True; on_delete=models.PROTECT; related_name='applied_snapshot'
state | models.JSONField |  | 
created_at | models.DateTimeField |  | db_index=True

Model metadata: `{"ordering": "['-version']"}`

## core/models.py::EmergencyAccessGrant

[[F:core/models.py#4584-4628#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
user | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.CASCADE; related_name='emergency_access_grants'
workflow | models.CharField |  | max_length=40; choices=AccessGrant.WORKFLOW_CHOICES; db_index=True
role | models.CharField |  | max_length=80
branch | models.CharField |  | max_length=120; blank=True
product | models.CharField |  | max_length=120; blank=True
product_ref | models.ForeignKey | 'Product' | null=True; blank=True; on_delete=models.PROTECT; related_name='emergency_access_grants'
group_configuration | models.ForeignKey | 'GroupSheetConfiguration' | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
reason | models.TextField |  | 
request_id | models.CharField |  | max_length=128; blank=True; db_index=True
activated_by | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='activated_emergency_access'
activated_at | models.DateTimeField |  | 
expires_at | models.DateTimeField |  | db_index=True
revoked_at | models.DateTimeField |  | null=True; blank=True
revoked_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='revoked_emergency_access'
revocation_reason | models.TextField |  | blank=True

Model metadata: `{"ordering": "['-activated_at']", "indexes": "[models.Index(fields=['user', 'workflow', 'expires_at'])]", "constraints": "[models.UniqueConstraint(fields=['activated_by', 'request_id'], condition=~models.Q(request_id=''), name='unique_emergency_access_request_id')]"}`

## core/models.py::StaffLifecycleChangePlan

[[F:core/models.py#4631-4729#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
action | models.CharField |  | max_length=32; choices=ACTION_CHOICES; db_index=True
target_user | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='staff_lifecycle_plans'
status | models.CharField |  | max_length=16; choices=STATUS_CHOICES; db_index=True
before_snapshot | models.JSONField |  | blank=True
proposed_snapshot | models.JSONField |  | blank=True
impact | models.JSONField |  | blank=True
expected_policy_version | models.PositiveIntegerField |  | 
reason | models.TextField |  | 
request_key | models.CharField |  | max_length=128; blank=True; db_index=True
request_fingerprint | models.CharField |  | max_length=64; blank=True
decision_mode | models.CharField |  | max_length=24; choices=DECISION_MODE_CHOICES; db_index=True
requested_by | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='requested_staff_lifecycle_plans'
requested_at | models.DateTimeField |  | db_index=True
effective_at | models.DateTimeField |  | null=True; blank=True; db_index=True
reviewed_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='reviewed_staff_lifecycle_plans'
reviewed_at | models.DateTimeField |  | null=True; blank=True
review_comment | models.TextField |  | blank=True
applied_at | models.DateTimeField |  | null=True; blank=True
error | models.CharField |  | max_length=500; blank=True

Model metadata: `{"ordering": "['-requested_at']", "constraints": "[models.UniqueConstraint(fields=['target_user'], condition=models.Q(status__in=['draft', 'pending', 'scheduled']), name='unique_open_staff_lifecycle_plan'), models.UniqueConstraint(fields=['requested_by', 'request_key'], condition=~models.Q(request_key=''), name='unique_staff_lifecycle_request_key')]"}`

## core/models.py::TelegramStaffActivation

[[F:core/models.py#4732-4762#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
user | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.CASCADE; related_name='telegram_staff_activations'
code_digest | models.CharField |  | max_length=128
expires_at | models.DateTimeField |  | db_index=True
failed_attempts | models.PositiveSmallIntegerField |  | 
consumed_at | models.DateTimeField |  | null=True; blank=True
invalidated_at | models.DateTimeField |  | null=True; blank=True
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='created_telegram_staff_activations'
created_at | models.DateTimeField |  | db_index=True

Model metadata: `{"ordering": "['-created_at']", "indexes": "[models.Index(fields=['user', 'expires_at'])]"}`

## core/models.py::StaffTelegramOnboarding

[[F:core/models.py#4765-4798#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
plan | models.OneToOneField | StaffLifecycleChangePlan | on_delete=models.CASCADE; related_name='telegram_onboarding'
user | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.CASCADE; related_name='telegram_onboardings'
status | models.CharField |  | max_length=32; choices=STATUS_CHOICES; db_index=True
revision | models.PositiveIntegerField |  | 
activated_at | models.DateTimeField |  | null=True; blank=True
welcome_sent_at | models.DateTimeField |  | null=True; blank=True
completed_at | models.DateTimeField |  | null=True; blank=True
last_error_code | models.CharField |  | max_length=80; blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-created_at']"}`

## core/models.py::StaffTelegramGroupInvitation

[[F:core/models.py#4801-4854#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
onboarding | models.ForeignKey | StaffTelegramOnboarding | on_delete=models.CASCADE; related_name='group_invitations'
group_configuration | models.ForeignKey | 'GroupSheetConfiguration' | on_delete=models.PROTECT; related_name='staff_onboarding_invitations'
status | models.CharField |  | max_length=32; choices=STATUS_CHOICES; db_index=True
launcher_ready_at | models.DateTimeField |  | null=True; blank=True
invite_created_at | models.DateTimeField |  | null=True; blank=True
invite_expires_at | models.DateTimeField |  | null=True; blank=True; db_index=True
invite_digest | models.CharField |  | max_length=64; blank=True
pending_invite_url | models.TextField |  | blank=True
joined_at | models.DateTimeField |  | null=True; blank=True
last_error_code | models.CharField |  | max_length=80; blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['group_configuration__display_name', 'pk']", "constraints": "[models.UniqueConstraint(fields=['onboarding', 'group_configuration'], name='unique_staff_onboarding_group_invite')]"}`

## core/models.py::AccessControlNotification

[[F:core/models.py#4857-4871#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
request | models.ForeignKey | AccessControlChangeRequest | null=True; blank=True; on_delete=models.CASCADE; related_name='notifications'
recipient | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
channel | models.CharField |  | max_length=16; choices=CHANNEL_CHOICES
event | models.CharField |  | max_length=64
status | models.CharField |  | max_length=16
error | models.TextField |  | blank=True
created_at | models.DateTimeField |  | 
delivered_at | models.DateTimeField |  | null=True; blank=True

Model metadata: `{}`

## core/models.py::UserHardDeletionBatch

[[F:core/models.py#4874-4922#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
request_id | models.CharField |  | max_length=128; unique=True; db_index=True
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.DO_NOTHING; related_name='+'
actor_label | models.CharField |  | max_length=255
reason_category | models.CharField |  | max_length=32; choices=REASON_CHOICES
reason_note | models.TextField |  | blank=True
target_count | models.PositiveIntegerField |  | 
preview_fingerprint | models.CharField |  | max_length=64
result_counts | models.JSONField |  | 
coverage_gaps | models.JSONField |  | blank=True
created_at | models.DateTimeField |  | db_index=True

Model metadata: `{"ordering": "['-created_at']"}`

## core/models.py::DeletedUserIdentity

[[F:core/models.py#4925-4955#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
batch | models.ForeignKey | UserHardDeletionBatch | on_delete=models.PROTECT; related_name='deleted_identities'
original_user_id | models.PositiveBigIntegerField |  | db_index=True
username | models.CharField |  | max_length=150
display_name | models.CharField |  | max_length=255; blank=True
was_active | models.BooleanField |  | 
was_staff | models.BooleanField |  | 
was_superuser | models.BooleanField |  | 
relationship_manifest | models.JSONField |  | 
deleted_at | models.DateTimeField |  | db_index=True

Model metadata: `{"ordering": "['-deleted_at']", "constraints": "[models.UniqueConstraint(fields=['batch', 'original_user_id'], name='unique_deleted_user_per_batch')]"}`

## core/models.py::CapabilityUsageDaily

[[F:core/models.py#4958-4970#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
day | models.DateField |  | db_index=True
user | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.CASCADE; related_name='+'
workflow | models.CharField |  | max_length=40; db_index=True
capability_key | models.CharField |  | max_length=120; db_index=True
use_count | models.PositiveIntegerField |  | 
last_used_at | models.DateTimeField |  | 

Model metadata: `{"constraints": "[models.UniqueConstraint(fields=['day', 'user', 'workflow', 'capability_key'], name='unique_daily_capability_usage')]", "indexes": "[models.Index(fields=['workflow', 'capability_key', 'day'])]"}`

## core/models.py::MiniAppDraft

[[F:core/models.py#4973-5009#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
user | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.CASCADE; related_name='miniapp_drafts'
workflow | models.CharField |  | max_length=40; db_index=True
context_key | models.CharField |  | max_length=180; db_index=True
payload | models.JSONField |  | 
revision | models.PositiveIntegerField |  | 
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 
expires_at | models.DateTimeField |  | db_index=True

Model metadata: `{"constraints": "[models.UniqueConstraint(fields=['user', 'workflow', 'context_key'], name='unique_miniapp_draft_context_per_user')]", "indexes": "[models.Index(fields=['workflow', 'context_key', 'expires_at']), models.Index(fields=['user', 'expires_at'])]"}`

## core/models.py::PortalVoiceTranscriptionAttempt

[[F:core/models.py#5014-5124#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
user | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='portal_voice_transcription_attempts'
farmer | models.ForeignKey | 'JawabuFarmerMaster' | on_delete=models.CASCADE; related_name='voice_transcription_attempts'; null=True; blank=True
complaint_group | models.ForeignKey | 'GroupSheetConfiguration' | on_delete=models.CASCADE; related_name='voice_transcription_attempts'; null=True; blank=True
complaint_case | models.ForeignKey | 'ParsedMessage' | on_delete=models.CASCADE; related_name='voice_transcription_attempts'; null=True; blank=True
field_name | models.CharField |  | max_length=64; choices=FIELD_CHOICES
request_id | models.CharField |  | max_length=128
audio_hash | models.CharField |  | max_length=64; db_index=True
audio_size | models.PositiveIntegerField |  | 
audio_mime_type | models.CharField |  | max_length=80; blank=True
duration_ms | models.PositiveIntegerField |  | 
provider | models.CharField |  | max_length=32
model_name | models.CharField |  | max_length=80
requested_language | models.CharField |  | max_length=8; db_index=True
detected_language | models.CharField |  | max_length=16; blank=True
average_log_probability | models.FloatField |  | null=True; blank=True
status | models.CharField |  | max_length=24; choices=STATUS_CHOICES; db_index=True
transcript | models.TextField |  | blank=True
provider_request_id | models.CharField |  | max_length=128; blank=True
drive_file_id | models.CharField |  | max_length=255; blank=True
expires_at | models.DateTimeField |  | db_index=True
resolved_at | models.DateTimeField |  | null=True; blank=True
edit_distance | models.PositiveIntegerField |  | null=True; blank=True
deletion_status | models.CharField |  | max_length=24; blank=True; db_index=True
deletion_error | models.CharField |  | max_length=255; blank=True
error_code | models.CharField |  | max_length=64; blank=True
source_attempt | models.ForeignKey | 'self' | null=True; blank=True; on_delete=models.SET_NULL; related_name='retries'
created_at | models.DateTimeField |  | db_index=True
updated_at | models.DateTimeField |  | 

Model metadata: `{"constraints": "[models.UniqueConstraint(fields=['user', 'request_id'], name='unique_portal_voice_request_per_user'), models.CheckConstraint(condition=models.Q(farmer__isnull=False, complaint_group__isnull=True, complaint_case__isnull=True) \| models.Q(farmer__isnull=True, complaint_group__isnull=False), name='voice_attempt_has_one_workflow_subject')]", "indexes": "[models.Index(fields=['user', 'created_at'], name='portal_voice_user_day_idx'), models.Index(fields=['status', 'expires_at'], name='portal_voice_status_exp_idx'), models.Index(fields=['farmer', 'field_name', 'created_at'], name='portal_voice_case_field_idx'), models.Index(fields=['complaint_group', 'field_name', 'created_at'], name='voice_complaint_group_idx'), models.Index(fields=['complaint_case', 'field_name', 'created_at'], name='voice_complaint_case_idx')]"}`

## core/models.py::JawabuFarmerUploadBatch

[[F:core/models.py#5127-5248#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
group_id | models.CharField |  | max_length=100; db_index=True
telegram_message_id | models.CharField |  | max_length=255; blank=True; db_index=True
sender | models.CharField |  | max_length=255; blank=True
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='jawabu_import_batches'
upload_request_id | models.CharField |  | max_length=128; null=True; blank=True; unique=True
source_filename | models.CharField |  | max_length=255; blank=True
source_mime_type | models.CharField |  | max_length=255; blank=True
source_size | models.PositiveIntegerField |  | 
source_content_hash | models.CharField |  | max_length=64; blank=True; db_index=True
source_content | models.BinaryField |  | blank=True; null=True
worklist_id | models.UUIDField |  | db_index=True
period_month | models.DateField |  | null=True; blank=True; db_index=True
version_number | models.PositiveIntegerField |  | 
is_current_version | models.BooleanField |  | db_index=True
reconciliation | models.JSONField |  | blank=True
archive_file_id | models.CharField |  | max_length=255; blank=True
archive_url | models.URLField |  | max_length=1000; blank=True
archive_error | models.TextField |  | blank=True
archive_sync_attempts | models.PositiveIntegerField |  | 
archive_last_sync_at | models.DateTimeField |  | null=True; blank=True
archive_next_retry_at | models.DateTimeField |  | null=True; blank=True
is_portal_archived | models.BooleanField |  | db_index=True
portal_archived_at | models.DateTimeField |  | null=True; blank=True; db_index=True
portal_archived_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='archived_portal_import_batches'
import_kind | models.CharField |  | max_length=32; choices=IMPORT_KIND_CHOICES; db_index=True
status | models.CharField |  | max_length=32; choices=STATUS_CHOICES; db_index=True
total_rows | models.PositiveIntegerField |  | 
review_needed | models.PositiveIntegerField |  | 
committed_count | models.PositiveIntegerField |  | 
skipped_count | models.PositiveIntegerField |  | 
parsed_rows | models.JSONField |  | blank=True
mapping | models.JSONField |  | blank=True
portal_revision | models.PositiveIntegerField |  | 
portal_commit_replays | models.JSONField |  | blank=True
error | models.TextField |  | blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 
committed_at | models.DateTimeField |  | null=True; blank=True

Model metadata: `{"ordering": "['-created_at']", "indexes": "[models.Index(fields=['group_id', 'created_at']), models.Index(fields=['status', 'created_at']), models.Index(fields=['archive_next_retry_at']), models.Index(fields=['is_portal_archived', 'group_id', 'created_at']), models.Index(fields=['worklist_id', 'version_number'], name='farmup_worklist_version_idx'), models.Index(fields=['group_id', 'period_month', 'is_current_version'], name='farmup_grp_period_cur_idx')]", "constraints": "[models.UniqueConstraint(fields=['worklist_id', 'version_number'], name='farmup_uq_worklist_ver'), models.UniqueConstraint(fields=['group_id', 'period_month'], condition=models.Q(import_kind='farmers', is_current_version=True, period_month__isnull=False), name='farmup_uq_current_period')]"}`

## core/models.py::FcaImportRecord

[[F:core/models.py#5250-5297#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
group_id | models.CharField |  | max_length=100; db_index=True
sheet_id | models.CharField |  | max_length=255; blank=True; db_index=True
sheet_tab | models.CharField |  | max_length=255; blank=True
row_number | models.PositiveIntegerField |  | null=True; blank=True
telegram_message_id | models.CharField |  | max_length=255; blank=True; db_index=True
source_filename | models.CharField |  | max_length=255; blank=True; db_index=True
source_sheet | models.CharField |  | max_length=255; blank=True
source_row | models.PositiveIntegerField |  | null=True; blank=True
sender | models.CharField |  | max_length=255; blank=True
customer_name | models.CharField |  | max_length=255; blank=True; db_index=True
primary_phone | models.CharField |  | max_length=32; blank=True; db_index=True
fca_visit_date | models.DateField |  | null=True; blank=True
fca_comment | models.TextField |  | blank=True
fca_decision | models.CharField |  | max_length=80; blank=True; db_index=True
import_status | models.CharField |  | max_length=32; choices=IMPORT_STATUS_CHOICES
parsed_fields | models.JSONField |  | blank=True
sync_error | models.TextField |  | blank=True
created_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-created_at']", "indexes": "[models.Index(fields=['group_id', 'created_at']), models.Index(fields=['group_id', 'source_filename', 'source_sheet', 'source_row']), models.Index(fields=['primary_phone', 'customer_name']), models.Index(fields=['import_status', 'fca_decision'])]"}`

## core/models.py::OperationalLocation

[[F:core/models.py#5300-5382#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
location_type | models.CharField |  | max_length=20; choices=LOCATION_TYPES; db_index=True
name | models.CharField |  | max_length=128
code | models.CharField |  | max_length=64
parent | models.ForeignKey | 'self' | null=True; blank=True; on_delete=models.PROTECT; related_name='children'
active | models.BooleanField |  | db_index=True
sort_order | models.PositiveIntegerField |  | 
source_name | models.CharField |  | max_length=160; blank=True
source_reference | models.URLField |  | max_length=1000; blank=True
published_at | models.DateTimeField |  | 
retired_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['location_type', 'sort_order', 'name']", "constraints": "[models.UniqueConstraint(Lower('name'), 'location_type', condition=models.Q(location_type__in=['branch', 'county']), name='unique_operational_location_name_ci'), models.UniqueConstraint(Lower('name'), 'parent', condition=models.Q(location_type='sub_county'), name='unique_sub_county_name_per_county_ci'), models.UniqueConstraint(Lower('code'), name='unique_operational_location_code_ci'), models.CheckConstraint(condition=~models.Q(code=''), name='operational_location_code_required')]"}`

## core/models.py::OperationalLocationAlias

[[F:core/models.py#5385-5454#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
location | models.ForeignKey | OperationalLocation | on_delete=models.PROTECT; related_name='aliases'
location_type | models.CharField |  | max_length=20; choices=OperationalLocation.LOCATION_TYPES
parent | models.ForeignKey | OperationalLocation | null=True; blank=True; on_delete=models.PROTECT; related_name='+'
alias | models.CharField |  | max_length=160
normalized_alias | models.CharField |  | max_length=180; db_index=True
active | models.BooleanField |  | db_index=True
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='+'
created_at | models.DateTimeField |  | 
retired_at | models.DateTimeField |  | null=True; blank=True

Model metadata: `{"ordering": "['location_type', 'alias']", "constraints": "[models.UniqueConstraint(fields=['location_type', 'normalized_alias'], condition=models.Q(location_type__in=['branch', 'county']), name='unique_location_alias_by_type'), models.UniqueConstraint(fields=['parent', 'normalized_alias'], condition=models.Q(location_type='sub_county'), name='unique_sub_county_alias_per_county')]"}`

## core/models.py::BranchServiceArea

[[F:core/models.py#5457-5516#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
branch | models.ForeignKey | OperationalLocation | on_delete=models.PROTECT; related_name='service_area_assignments'
area | models.ForeignKey | OperationalLocation | on_delete=models.PROTECT; related_name='serving_branch_assignments'
is_primary | models.BooleanField |  | db_index=True
active | models.BooleanField |  | db_index=True
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='created_branch_service_areas'
retired_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='retired_branch_service_areas'
created_at | models.DateTimeField |  | 
retired_at | models.DateTimeField |  | null=True; blank=True

Model metadata: `{"ordering": "['branch__sort_order', 'branch__name', 'area__sort_order', 'area__name']", "constraints": "[models.UniqueConstraint(fields=['branch', 'area'], name='unique_branch_service_area'), models.UniqueConstraint(fields=['area'], condition=models.Q(active=True, is_primary=True), name='unique_active_primary_branch_per_area')]"}`

## core/models.py::LocationPolicyState

[[F:core/models.py#5519-5544#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.PositiveSmallIntegerField |  | primary_key=True
mode | models.CharField |  | max_length=16; choices=MODE_CHOICES; db_index=True
source_manifest | models.JSONField |  | blank=True
updated_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='+'
updated_at | models.DateTimeField |  | 

Model metadata: `{}`

## core/models.py::LocationConfigurationEvent

[[F:core/models.py#5547-5571#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
subject_type | models.CharField |  | max_length=40; db_index=True
subject_id | models.CharField |  | max_length=120; db_index=True
action | models.CharField |  | max_length=60; db_index=True
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='+'
request_id | models.CharField |  | max_length=128; blank=True; db_index=True
before_values | models.JSONField |  | blank=True
after_values | models.JSONField |  | blank=True
occurred_at | models.DateTimeField |  | db_index=True

Model metadata: `{"ordering": "['occurred_at', 'id']"}`

## core/models.py::LocationMappingIssue

[[F:core/models.py#5574-5618#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
location_type | models.CharField |  | max_length=20; choices=OperationalLocation.LOCATION_TYPES; db_index=True
raw_value | models.CharField |  | max_length=255
normalized_value | models.CharField |  | max_length=180; db_index=True
source_workflow | models.CharField |  | max_length=40; db_index=True
source_model | models.CharField |  | max_length=120
source_field | models.CharField |  | max_length=80
source_record_id | models.CharField |  | max_length=120
status | models.CharField |  | max_length=16; choices=STATUS_CHOICES; db_index=True
location | models.ForeignKey | OperationalLocation | null=True; blank=True; on_delete=models.PROTECT; related_name='mapping_issues'
detail | models.TextField |  | blank=True
resolved_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='+'
resolved_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-created_at']", "constraints": "[models.UniqueConstraint(fields=['location_type', 'normalized_value', 'source_model', 'source_field', 'source_record_id'], condition=models.Q(status='open'), name='unique_open_location_mapping_issue')]"}`

## core/models.py::GroupSheetConfiguration

[[F:core/models.py#5621-5734#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
group_id | models.CharField |  | max_length=100; unique=True; db_index=True
display_name | models.CharField |  | max_length=255; blank=True
enabled | models.BooleanField |  | 
tat_sheet_projection_enabled | models.BooleanField |  | 
complaint_sheet_projection_enabled | models.BooleanField |  | 
tat_sheet_projection_disabled_at | models.DateTimeField |  | null=True; blank=True
sheet_id | models.CharField |  | max_length=255; blank=True
sheet_name | models.CharField |  | max_length=255; blank=True
sheet_schema | models.JSONField |  | blank=True
workflow | models.JSONField |  | blank=True
parser_rules | models.JSONField |  | blank=True
metadata | models.JSONField |  | blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['group_id']"}`

## core/models.py::SheetRegisterContract

[[F:core/models.py#5737-5820#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
group_configuration | models.ForeignKey | GroupSheetConfiguration | on_delete=models.CASCADE; related_name='sheet_register_contracts'
register_key | models.CharField |  | max_length=80
sheet_name | models.CharField |  | max_length=255
publication_mode | models.CharField |  | max_length=32; choices=MODE_CHOICES
subject_type | models.CharField |  | max_length=32; choices=SUBJECT_CHOICES
header_row | models.PositiveIntegerField |  | 
data_start_row | models.PositiveIntegerField |  | 
row_key_header | models.CharField |  | max_length=255; blank=True
expected_headers | models.JSONField |  | blank=True
field_ownership | models.JSONField |  | blank=True
enabled | models.BooleanField |  | db_index=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['group_configuration__group_id', 'register_key']", "constraints": "[models.UniqueConstraint(fields=['group_configuration', 'register_key'], name='unique_sheet_register_contract_per_group')]", "indexes": "[models.Index(fields=['enabled', 'subject_type'])]"}`

## core/models.py::SheetSyncAuditSnapshot

[[F:core/models.py#5823-5864#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
contract | models.ForeignKey | SheetRegisterContract | on_delete=models.PROTECT; related_name='audit_snapshots'
status | models.CharField |  | max_length=32; choices=STATUS_CHOICES; db_index=True
expected_header_fingerprint | models.CharField |  | max_length=64; blank=True
actual_header_fingerprint | models.CharField |  | max_length=64; blank=True
missing_headers | models.JSONField |  | blank=True
duplicate_headers | models.JSONField |  | blank=True
reordered_headers | models.BooleanField |  | 
rows_checked | models.PositiveIntegerField |  | 
discrepancy_count | models.PositiveIntegerField |  | 
error_code | models.CharField |  | max_length=80; blank=True
error | models.TextField |  | blank=True
checked_by | models.CharField |  | max_length=255; blank=True
created_at | models.DateTimeField |  | db_index=True

Model metadata: `{"ordering": "['-created_at']", "indexes": "[models.Index(fields=['contract', 'created_at']), models.Index(fields=['status', 'created_at'])]"}`

## core/models.py::SheetSyncDiscrepancy

[[F:core/models.py#5867-5903#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
snapshot | models.ForeignKey | SheetSyncAuditSnapshot | on_delete=models.CASCADE; related_name='discrepancies'
record_key | models.CharField |  | max_length=255; blank=True; db_index=True
field_name | models.CharField |  | max_length=255; blank=True
kind | models.CharField |  | max_length=48; choices=KIND_CHOICES; db_index=True
expected_value_hash | models.CharField |  | max_length=64; blank=True
actual_value_hash | models.CharField |  | max_length=64; blank=True
detail | models.CharField |  | max_length=500; blank=True
created_at | models.DateTimeField |  | db_index=True

Model metadata: `{"ordering": "['kind', 'record_key', 'field_name']", "indexes": "[models.Index(fields=['snapshot', 'kind']), models.Index(fields=['record_key', 'kind'])]"}`

## core/models.py::TatTrackerApprovalCertificate

[[F:core/models.py#5906-5940#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
case | models.ForeignKey | TatTrackerCase | on_delete=models.CASCADE; related_name='approval_certificates'
event | models.OneToOneField | TatTrackerEvent | on_delete=models.PROTECT; related_name='approval_certificate'
staff_user | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; null=True; blank=True; related_name='tat_approval_certificates'
signer_name | models.CharField |  | max_length=255; blank=True
signer_telegram_id | models.CharField |  | max_length=100; blank=True
signer_national_id | models.CharField |  | max_length=40; blank=True
signer_phone_number | models.CharField |  | max_length=20; blank=True
signer_email | models.EmailField |  | blank=True
stage_key | models.CharField |  | max_length=120; db_index=True
external_reference | models.CharField |  | max_length=80; unique=True
status | models.CharField |  | max_length=32; choices=STATUS_CHOICES; db_index=True
signed_document_hash | models.CharField |  | max_length=64; blank=True
signed_document_path | models.TextField |  | blank=True
webhook_delivery_id | models.CharField |  | max_length=64; blank=True; unique=True; null=True
error | models.TextField |  | blank=True
signed_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"indexes": "[models.Index(fields=['case', 'stage_key'], name='core_tattra_case_id_61a8f6_idx'), models.Index(fields=['status', 'updated_at'], name='core_tattra_status_a6367e_idx')]"}`

## core/models.py::RequisitionBatch

[[F:core/models.py#5942-6046#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
group_configuration | models.ForeignKey | 'GroupSheetConfiguration' | null=True; blank=True; on_delete=models.PROTECT; related_name='requisition_batches'
fulfillment_partner | models.CharField |  | max_length=20; choices=[('HB', 'HB'), ('ECOCONSERVE', 'Eco-conserve')]; db_index=True
requisition_template | models.ForeignKey | 'RequisitionTemplate' | null=True; blank=True; on_delete=models.PROTECT; related_name='generated_batches'
order_number | models.CharField |  | max_length=128; db_index=True
generation_request_id | models.CharField |  | max_length=128; blank=True; db_index=True
version | models.PositiveIntegerField |  | db_index=True
preview_version | models.PositiveIntegerField |  | db_index=True
requisition_date | models.DateField |  | null=True; blank=True
generated_by | models.CharField |  | max_length=255; blank=True
filename | models.CharField |  | max_length=255; blank=True
content_type | models.CharField |  | max_length=255
file_content | models.BinaryField |  | blank=True
content_checksum | models.CharField |  | max_length=64; blank=True
membership_digest | models.CharField |  | max_length=64; blank=True
finalization_payload_digest | models.CharField |  | max_length=64; blank=True
finalized_at | models.DateTimeField |  | null=True; blank=True
finalized_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
drive_file_id | models.CharField |  | max_length=255; blank=True
drive_url | models.URLField |  | max_length=1000; blank=True
drive_upload_error | models.TextField |  | blank=True
drive_sync_attempts | models.PositiveIntegerField |  | 
drive_last_sync_at | models.DateTimeField |  | null=True; blank=True
drive_next_retry_at | models.DateTimeField |  | null=True; blank=True; db_index=True
preview_filename | models.CharField |  | max_length=255; blank=True
preview_drive_file_id | models.CharField |  | max_length=255; blank=True
preview_drive_url | models.URLField |  | max_length=1000; blank=True
preview_generated_by | models.CharField |  | max_length=255; blank=True
preview_generated_at | models.DateTimeField |  | null=True; blank=True
preview_error | models.TextField |  | blank=True
preview_drive_sync_attempts | models.PositiveIntegerField |  | 
preview_drive_last_sync_at | models.DateTimeField |  | null=True; blank=True
preview_drive_next_retry_at | models.DateTimeField |  | null=True; blank=True; db_index=True
farmer_ids | models.JSONField |  | blank=True
farmer_count | models.PositiveIntegerField |  | 
status | models.CharField |  | max_length=32; choices=STATUS_CHOICES; db_index=True
invoice_summary | models.JSONField |  | blank=True
last_invoice_result | models.JSONField |  | blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-requisition_date', '-updated_at']", "indexes": "[models.Index(fields=['order_number']), models.Index(fields=['status', 'updated_at'])]", "constraints": "[models.UniqueConstraint(fields=['generation_request_id'], condition=~models.Q(generation_request_id=''), name='unique_requisition_batch_generation_request')]"}`

## core/models.py::RequisitionTemplate

[[F:core/models.py#6049-6096#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
name | models.CharField |  | max_length=255
fulfillment_partner | models.CharField |  | max_length=20; choices=[('HB', 'HB'), ('ECOCONSERVE', 'Eco-conserve')]; db_index=True
file | models.FileField |  | 
original_filename | models.CharField |  | max_length=255; blank=True
content_type | models.CharField |  | max_length=255; blank=True
size | models.PositiveIntegerField |  | 
checksum | models.CharField |  | max_length=64; blank=True
drive_file_id | models.CharField |  | max_length=255; blank=True
drive_url | models.URLField |  | max_length=1000; blank=True
drive_uploaded_at | models.DateTimeField |  | null=True; blank=True
drive_upload_error | models.TextField |  | blank=True
is_active | models.BooleanField |  | 
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-is_active', '-updated_at']"}`

## core/models.py::PaymentDocumentTemplate

[[F:core/models.py#6099-6139#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
name | models.CharField |  | max_length=255
file | models.FileField |  | 
original_filename | models.CharField |  | max_length=255; blank=True
content_type | models.CharField |  | max_length=255; blank=True
size | models.PositiveIntegerField |  | 
checksum | models.CharField |  | max_length=64; blank=True
drive_file_id | models.CharField |  | max_length=255; blank=True
drive_url | models.URLField |  | max_length=1000; blank=True
drive_uploaded_at | models.DateTimeField |  | null=True; blank=True
drive_upload_error | models.TextField |  | blank=True
is_active | models.BooleanField |  | 
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-is_active', '-updated_at']"}`

## core/models.py::InvoiceUploadBatch

[[F:core/models.py#6142-6204#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
group_configuration | models.ForeignKey | 'GroupSheetConfiguration' | null=True; blank=True; on_delete=models.PROTECT; related_name='portal_invoice_uploads'
original_filename | models.CharField |  | max_length=255; blank=True
content_type | models.CharField |  | max_length=255; blank=True
size | models.PositiveIntegerField |  | 
uploaded_by | models.CharField |  | max_length=255; blank=True
client_request_id | models.CharField |  | max_length=128; blank=True; db_index=True
content_sha256 | models.CharField |  | max_length=64; blank=True
order_number | models.CharField |  | max_length=128; blank=True; db_index=True
drive_file_id | models.CharField |  | max_length=255; blank=True
drive_url | models.URLField |  | max_length=1000; blank=True
status | models.CharField |  | max_length=32; choices=STATUS_CHOICES; db_index=True
total_pages | models.PositiveIntegerField |  | 
total_parsed | models.PositiveIntegerField |  | 
matched_count | models.PositiveIntegerField |  | 
unmatched_count | models.PositiveIntegerField |  | 
error | models.TextField |  | blank=True
sync_status | models.CharField |  | max_length=32; blank=True; db_index=True
sync_error | models.TextField |  | blank=True
metadata | models.JSONField |  | blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-created_at']", "indexes": "[models.Index(fields=['status', 'created_at']), models.Index(fields=['uploaded_by', 'created_at'])]", "constraints": "[models.UniqueConstraint(fields=['client_request_id'], condition=~models.Q(client_request_id=''), name='unique_invoice_upload_client_request'), models.UniqueConstraint(fields=['group_configuration', 'content_sha256'], condition=~models.Q(content_sha256=''), name='unique_group_invoice_pdf_hash')]"}`

## core/models.py::ParsedInvoice

[[F:core/models.py#6207-6271#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
batch | models.ForeignKey | InvoiceUploadBatch | on_delete=models.CASCADE; related_name='invoices'
page | models.PositiveIntegerField |  | 
invoice_no | models.CharField |  | max_length=128; blank=True; db_index=True
invoice_date_raw | models.CharField |  | max_length=64; blank=True
invoice_date | models.DateField |  | null=True; blank=True
customer_name | models.CharField |  | max_length=255; blank=True; db_index=True
customer_id | models.CharField |  | max_length=64; blank=True; db_index=True
customer_phone | models.CharField |  | max_length=64; blank=True; db_index=True
invoice_amount | models.DecimalField |  | max_digits=12; decimal_places=2; null=True; blank=True
total_after_discount | models.DecimalField |  | max_digits=12; decimal_places=2; null=True; blank=True
discount | models.DecimalField |  | max_digits=12; decimal_places=2; null=True; blank=True
payment | models.DecimalField |  | max_digits=12; decimal_places=2; null=True; blank=True
balance_due | models.DecimalField |  | max_digits=12; decimal_places=2; null=True; blank=True
balance_due_check | models.CharField |  | max_length=128; blank=True
calculated_balance_due | models.DecimalField |  | max_digits=12; decimal_places=2; null=True; blank=True
balance_due_difference | models.DecimalField |  | max_digits=12; decimal_places=2; null=True; blank=True
balance_due_check_basis | models.CharField |  | max_length=128; blank=True
status | models.CharField |  | max_length=32; choices=STATUS_CHOICES; db_index=True
matched_farmer | models.ForeignKey | JawabuFarmerMaster | on_delete=models.SET_NULL; null=True; blank=True; related_name='parsed_invoices'
proposed_farmer | models.ForeignKey | JawabuFarmerMaster | on_delete=models.SET_NULL; null=True; blank=True; related_name='proposed_invoices'
proposed_order_number | models.CharField |  | max_length=128; blank=True; db_index=True
matched_order_number | models.CharField |  | max_length=128; blank=True; db_index=True
raw_payload | models.JSONField |  | blank=True
review_notes | models.TextField |  | blank=True
revision | models.PositiveIntegerField |  | 
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-created_at']", "indexes": "[models.Index(fields=['status', 'created_at']), models.Index(fields=['matched_order_number', 'status'])]"}`

## core/models.py::ParsedInvoiceEvent

[[F:core/models.py#6274-6306#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
invoice | models.ForeignKey | ParsedInvoice | on_delete=models.CASCADE; related_name='events'
action | models.CharField |  | max_length=32; choices=ACTION_CHOICES; db_index=True
actor | models.CharField |  | max_length=255; blank=True
note | models.TextField |  | blank=True
metadata | models.JSONField |  | blank=True
created_at | models.DateTimeField |  | db_index=True

Model metadata: `{"ordering": "['-created_at']", "indexes": "[models.Index(fields=['invoice', 'created_at']), models.Index(fields=['action', 'created_at'])]"}`

## core/models.py::InvoiceIdentityReview

[[F:core/models.py#6309-6354#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
invoice | models.ForeignKey | ParsedInvoice | on_delete=models.CASCADE; related_name='identity_reviews'
farmer | models.ForeignKey | JawabuFarmerMaster | on_delete=models.CASCADE; related_name='invoice_identity_reviews'
status | models.CharField |  | max_length=40; choices=STATUS_CHOICES; db_index=True
discrepancy_codes | models.JSONField |  | blank=True
invoice_identity | models.JSONField |  | blank=True
applicant_identity | models.JSONField |  | blank=True
decision_note | models.TextField |  | blank=True
decided_by | models.CharField |  | max_length=255; blank=True
decided_at | models.DateTimeField |  | null=True; blank=True
client_request_id | models.CharField |  | max_length=128; blank=True; db_index=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-created_at']", "constraints": "[models.UniqueConstraint(fields=['invoice'], condition=models.Q(status='pending'), name='unique_pending_invoice_identity_review'), models.UniqueConstraint(fields=['client_request_id'], condition=~models.Q(client_request_id=''), name='unique_invoice_identity_review_request')]"}`

## core/models.py::JawabuRelatedPerson

[[F:core/models.py#6357-6370#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
linked_customer | models.ForeignKey | JawabuCustomer | on_delete=models.SET_NULL; null=True; blank=True; related_name='related_person_profiles'
full_name | models.CharField |  | max_length=255
national_id | models.CharField |  | max_length=64; blank=True; db_index=True
primary_phone | models.CharField |  | max_length=64; blank=True; db_index=True
source | models.CharField |  | max_length=255; blank=True
created_by | models.CharField |  | max_length=255; blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{}`

## core/models.py::JawabuHouseholdRelationship

[[F:core/models.py#6373-6402#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
farmer | models.ForeignKey | JawabuFarmerMaster | on_delete=models.CASCADE; related_name='household_relationships'
related_person | models.ForeignKey | JawabuRelatedPerson | on_delete=models.PROTECT; related_name='relationships'
relationship_type | models.CharField |  | max_length=32; choices=TYPE_CHOICES
status | models.CharField |  | max_length=16; choices=STATUS_CHOICES; db_index=True
attestation_note | models.TextField |  | 
evidence_reference | models.CharField |  | max_length=1000
confirmed_by | models.CharField |  | max_length=255
confirmed_at | models.DateTimeField |  | 
revoked_by | models.CharField |  | max_length=255; blank=True
revoked_at | models.DateTimeField |  | null=True; blank=True
revocation_reason | models.TextField |  | blank=True
created_at | models.DateTimeField |  | 

Model metadata: `{"constraints": "[models.UniqueConstraint(fields=['farmer', 'related_person', 'relationship_type'], condition=models.Q(status='confirmed'), name='unique_confirmed_household_relationship')]"}`

## core/models.py::InvoiceNameChangeBatch

[[F:core/models.py#6405-6445#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
reference | models.CharField |  | max_length=128; blank=True; db_index=True
status | models.CharField |  | max_length=32; choices=STATUS_CHOICES; db_index=True
letter_file_reference | models.CharField |  | max_length=1000; blank=True
letter_checksum | models.CharField |  | max_length=128; blank=True
sent_artifact | models.ForeignKey | 'InvoiceNameChangeLetterArtifact' | on_delete=models.PROTECT; null=True; blank=True; related_name='sent_for_batches'
legacy_manual_letter_allowed | models.BooleanField |  | 
sent_reference | models.CharField |  | max_length=255; blank=True
created_by | models.CharField |  | max_length=255
sent_by | models.CharField |  | max_length=255; blank=True
sent_at | models.DateTimeField |  | null=True; blank=True
revision | models.PositiveIntegerField |  | 
client_request_id | models.CharField |  | max_length=128; blank=True; db_index=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-created_at']", "constraints": "[models.UniqueConstraint(fields=['client_request_id'], condition=~models.Q(client_request_id=''), name='unique_invoice_name_change_batch_request')]"}`

## core/models.py::InvoiceNameChangeLetterTemplate

[[F:core/models.py#6448-6495#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
template_key | models.CharField |  | max_length=64
name | models.CharField |  | max_length=255
file | models.FileField |  | 
original_filename | models.CharField |  | max_length=255; blank=True
content_type | models.CharField |  | max_length=255
size | models.PositiveIntegerField |  | 
checksum | models.CharField |  | max_length=64; blank=True
drive_file_id | models.CharField |  | max_length=255; blank=True
drive_url | models.URLField |  | max_length=1000; blank=True
drive_uploaded_at | models.DateTimeField |  | null=True; blank=True
drive_upload_error | models.TextField |  | blank=True
is_active | models.BooleanField |  | db_index=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-is_active', '-updated_at']", "constraints": "[models.UniqueConstraint(fields=['template_key'], condition=models.Q(is_active=True), name='unique_active_invoice_name_change_template')]"}`

## core/models.py::InvoiceNameChangeLetterArtifact

[[F:core/models.py#6498-6582#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
batch | models.ForeignKey | InvoiceNameChangeBatch | on_delete=models.PROTECT; related_name='letter_artifacts'
template | models.ForeignKey | InvoiceNameChangeLetterTemplate | on_delete=models.PROTECT; related_name='generated_artifacts'
version | models.PositiveIntegerField |  | 
status | models.CharField |  | max_length=24; choices=STATUS_CHOICES; db_index=True
filename | models.CharField |  | max_length=255
content_type | models.CharField |  | max_length=255
file_content | models.BinaryField |  | blank=True
checksum | models.CharField |  | max_length=64
preview_filename | models.CharField |  | max_length=255; blank=True
preview_content_type | models.CharField |  | max_length=255
preview_file_content | models.BinaryField |  | blank=True
preview_checksum | models.CharField |  | max_length=64; blank=True
template_checksum | models.CharField |  | max_length=64
source_fingerprint | models.CharField |  | max_length=64; db_index=True
payload_snapshot | models.JSONField |  | 
generated_by | models.CharField |  | max_length=255
generated_at | models.DateTimeField |  | 
client_request_id | models.CharField |  | max_length=128; blank=True; db_index=True
drive_file_id | models.CharField |  | max_length=255; blank=True
drive_url | models.URLField |  | max_length=1000; blank=True
drive_upload_error | models.TextField |  | blank=True
drive_sync_attempts | models.PositiveIntegerField |  | 
drive_last_sync_at | models.DateTimeField |  | null=True; blank=True
drive_next_retry_at | models.DateTimeField |  | null=True; blank=True; db_index=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-version', '-created_at']", "constraints": "[models.UniqueConstraint(fields=['batch', 'version'], name='unique_invoice_name_change_letter_version'), models.UniqueConstraint(fields=['batch', 'client_request_id'], condition=~models.Q(client_request_id=''), name='unique_invoice_name_change_letter_request')]"}`

## core/models.py::InvoiceNameChangeItem

[[F:core/models.py#6585-6634#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
batch | models.ForeignKey | InvoiceNameChangeBatch | on_delete=models.PROTECT; related_name='items'; null=True; blank=True
review | models.OneToOneField | InvoiceIdentityReview | on_delete=models.PROTECT; related_name='name_change_item'
farmer | models.ForeignKey | JawabuFarmerMaster | on_delete=models.PROTECT; related_name='invoice_name_changes'
relationship | models.ForeignKey | JawabuHouseholdRelationship | on_delete=models.PROTECT; related_name='invoice_name_changes'
original_invoice | models.ForeignKey | ParsedInvoice | on_delete=models.PROTECT; related_name='name_change_requests'
replacement_invoice | models.ForeignKey | ParsedInvoice | on_delete=models.PROTECT; null=True; blank=True; related_name='replacement_for_name_changes'
status | models.CharField |  | max_length=32; choices=STATUS_CHOICES; db_index=True
original_identity | models.JSONField |  | blank=True
requested_identity | models.JSONField |  | blank=True
completed_by | models.CharField |  | max_length=255; blank=True
completed_at | models.DateTimeField |  | null=True; blank=True
closed_reason | models.TextField |  | blank=True
hb_communication_reference | models.CharField |  | max_length=255; blank=True
closed_by | models.CharField |  | max_length=255; blank=True
closed_at | models.DateTimeField |  | null=True; blank=True
follow_up_of | models.ForeignKey | 'self' | on_delete=models.PROTECT; null=True; blank=True; related_name='follow_ups'
client_request_id | models.CharField |  | max_length=128; blank=True; db_index=True
revision | models.PositiveIntegerField |  | 
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"constraints": "[models.UniqueConstraint(fields=['original_invoice'], condition=models.Q(status__in=['draft', 'awaiting_replacement']), name='unique_open_invoice_name_change'), models.UniqueConstraint(fields=['client_request_id'], condition=~models.Q(client_request_id=''), name='unique_invoice_name_change_item_request')]"}`

## core/models.py::PaymentDocument

[[F:core/models.py#6637-6717#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
order_number | models.CharField |  | max_length=128; db_index=True
payment_number | models.CharField |  | max_length=32; blank=True; db_index=True
status | models.CharField |  | max_length=32; choices=STATUS_CHOICES; db_index=True
version | models.PositiveIntegerField |  | 
filename | models.CharField |  | max_length=255; blank=True
content_type | models.CharField |  | max_length=255
file_content | models.BinaryField |  | blank=True
drive_file_id | models.CharField |  | max_length=255; blank=True
drive_url | models.URLField |  | max_length=1000; blank=True
drive_sync_attempts | models.PositiveIntegerField |  | 
drive_last_sync_at | models.DateTimeField |  | null=True; blank=True
drive_next_retry_at | models.DateTimeField |  | null=True; blank=True; db_index=True
generated_by | models.CharField |  | max_length=255; blank=True
reviewed_by | models.CharField |  | max_length=255; blank=True
reviewed_at | models.DateTimeField |  | null=True; blank=True
call_up_comments | models.TextField |  | blank=True
case_call_up_comments | models.JSONField |  | blank=True
finalized_by | models.CharField |  | max_length=255; blank=True
row_count | models.PositiveIntegerField |  | 
farmer_ids | models.JSONField |  | blank=True
invoice_batch_ids | models.JSONField |  | blank=True
validation_summary | models.JSONField |  | blank=True
error | models.TextField |  | blank=True
finalized_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-created_at']", "indexes": "[models.Index(fields=['order_number', 'status']), models.Index(fields=['status', 'created_at'])]", "constraints": "[models.UniqueConstraint(fields=['order_number', 'version'], condition=models.Q(status='final'), name='unique_final_payment_document_version')]"}`

## core/models.py::DocumentSignoffPolicy

[[F:core/models.py#6720-6778#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
document_type | models.CharField |  | max_length=24; choices=DOCUMENT_TYPE_CHOICES; unique=True
workflow | models.CharField |  | max_length=40; choices=AccessGrant.WORKFLOW_CHOICES
approval_role | models.CharField |  | max_length=80
approval_roles | models.JSONField |  | blank=True
is_active | models.BooleanField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['document_type']"}`

## core/models.py::DocumentPhysicalSignoff

[[F:core/models.py#6781-6906#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
document_type | models.CharField |  | max_length=24; choices=DOCUMENT_TYPE_CHOICES; db_index=True
requisition_batch | models.ForeignKey | RequisitionBatch | null=True; blank=True; on_delete=models.PROTECT; related_name='physical_signoffs'
payment_document | models.ForeignKey | PaymentDocument | null=True; blank=True; on_delete=models.PROTECT; related_name='physical_signoffs'
source_version | models.PositiveIntegerField |  | 
source_filename | models.CharField |  | max_length=255
source_content_type | models.CharField |  | max_length=255
source_checksum | models.CharField |  | max_length=64; db_index=True
source_file_content | models.BinaryField |  | blank=True
scan_filename | models.CharField |  | max_length=255
scan_content_type | models.CharField |  | max_length=255
scan_size | models.PositiveIntegerField |  | 
scan_checksum | models.CharField |  | max_length=64; db_index=True
scan_file_content | models.BinaryField |  | blank=True
drive_file_id | models.CharField |  | max_length=255; blank=True
drive_url | models.URLField |  | max_length=1000; blank=True
drive_sync_attempts | models.PositiveIntegerField |  | 
drive_last_sync_at | models.DateTimeField |  | null=True; blank=True
drive_next_retry_at | models.DateTimeField |  | null=True; blank=True; db_index=True
drive_upload_error | models.TextField |  | blank=True
status | models.CharField |  | max_length=32; choices=STATUS_CHOICES; db_index=True
attested_complete | models.BooleanField |  | 
uploaded_by | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='uploaded_physical_document_signoffs'
approved_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='approved_physical_document_signoffs'
approved_at | models.DateTimeField |  | null=True; blank=True
rejection_reason | models.TextField |  | blank=True
request_id | models.CharField |  | max_length=128; blank=True; db_index=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-created_at']", "indexes": "[models.Index(fields=['document_type', 'status', 'created_at']), models.Index(fields=['requisition_batch', 'source_version']), models.Index(fields=['payment_document', 'source_version'])]", "constraints": "[models.CheckConstraint(condition=models.Q(document_type='requisition', requisition_batch__isnull=False, payment_document__isnull=True) \| models.Q(document_type='payment', requisition_batch__isnull=True, payment_document__isnull=False), name='document_signoff_matches_artifact_type'), models.UniqueConstraint(fields=['request_id'], condition=~models.Q(request_id=''), name='unique_document_signoff_request_id'), models.UniqueConstraint(fields=['requisition_batch', 'source_version'], condition=models.Q(document_type='requisition', status='signed_approved'), name='unique_signed_requisition_version'), models.UniqueConstraint(fields=['payment_document', 'source_version'], condition=models.Q(document_type='payment', status='signed_approved'), name='unique_signed_payment_version')]"}`

## core/models.py::DocumentPhysicalSignoffEvent

[[F:core/models.py#6909-6939#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
signoff | models.ForeignKey | DocumentPhysicalSignoff | on_delete=models.CASCADE; related_name='events'
action | models.CharField |  | max_length=32; choices=ACTION_CHOICES; db_index=True
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
note | models.TextField |  | blank=True
metadata | models.JSONField |  | blank=True
created_at | models.DateTimeField |  | db_index=True

Model metadata: `{"ordering": "['-created_at']", "indexes": "[models.Index(fields=['signoff', 'created_at'])]"}`

## core/models.py::ComplianceAuditChainState

[[F:core/models.py#6942-6952#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
singleton | models.PositiveSmallIntegerField |  | primary_key=True
last_position | models.PositiveBigIntegerField |  | 
last_hash | models.CharField |  | max_length=64; blank=True
updated_at | models.DateTimeField |  | 

Model metadata: `{}`

## core/models.py::ComplianceAuditEvent

[[F:core/models.py#6955-7052#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
workflow | models.CharField |  | max_length=40; choices=WORKFLOW_CHOICES; db_index=True
action | models.CharField |  | max_length=120; db_index=True
category | models.CharField |  | max_length=40; db_index=True
origin | models.CharField |  | max_length=24; choices=ORIGIN_CHOICES; db_index=True
subject_type | models.CharField |  | max_length=80; db_index=True
subject_id | models.CharField |  | max_length=128; db_index=True
customer_reference | models.CharField |  | max_length=128; blank=True; db_index=True
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.DO_NOTHING; related_name='compliance_audit_actions'
authority_user | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.DO_NOTHING; related_name='compliance_audit_authorizations'
actor_label | models.CharField |  | max_length=255; blank=True
authority_label | models.CharField |  | max_length=255; blank=True
request_id | models.CharField |  | max_length=128; blank=True; db_index=True
source_model | models.CharField |  | max_length=120; blank=True
source_event_id | models.CharField |  | max_length=160; blank=True
deduplication_key | models.CharField |  | max_length=255; unique=True; db_index=True
before_values | models.JSONField |  | blank=True
after_values | models.JSONField |  | blank=True
metadata | models.JSONField |  | blank=True
sensitive | models.BooleanField |  | db_index=True
retention_class | models.CharField |  | max_length=32; choices=RETENTION_CHOICES; db_index=True
occurred_at | models.DateTimeField |  | db_index=True
recorded_at | models.DateTimeField |  | db_index=True
chain_position | models.PositiveBigIntegerField |  | unique=True
previous_hash | models.CharField |  | max_length=64; blank=True
payload_hash | models.CharField |  | max_length=64
integrity_hash | models.CharField |  | max_length=64; unique=True

Model metadata: `{"ordering": "['-chain_position']", "indexes": "[models.Index(fields=['workflow', 'occurred_at']), models.Index(fields=['subject_type', 'subject_id', 'occurred_at']), models.Index(fields=['actor', 'occurred_at']), models.Index(fields=['action', 'occurred_at']), models.Index(fields=['sensitive', 'occurred_at'])]"}`

## core/models.py::ComplianceAuditCheckpoint

[[F:core/models.py#7055-7084#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
checkpoint_date | models.DateField |  | unique=True; db_index=True
chain_position | models.PositiveBigIntegerField |  | 
chain_hash | models.CharField |  | max_length=64; blank=True
event_count | models.PositiveBigIntegerField |  | 
recipient_fingerprint | models.CharField |  | max_length=64; blank=True
status | models.CharField |  | max_length=24; choices=STATUS_CHOICES; db_index=True
delivery_attempts | models.PositiveIntegerField |  | 
delivered_at | models.DateTimeField |  | null=True; blank=True
delivery_error | models.TextField |  | blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-checkpoint_date']"}`

## core/models.py::IntegrationOperation

[[F:core/models.py#7087-7156#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
integration | models.CharField |  | max_length=32; choices=INTEGRATION_CHOICES; db_index=True
operation_type | models.CharField |  | max_length=80; db_index=True
deduplication_key | models.CharField |  | max_length=255; unique=True; db_index=True
source_model | models.CharField |  | max_length=120; blank=True
source_id | models.CharField |  | max_length=128; blank=True; db_index=True
request_id | models.CharField |  | max_length=128; blank=True; db_index=True
requested_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='integration_operations'
requested_by_label | models.CharField |  | max_length=255; blank=True
payload_digest | models.CharField |  | max_length=64; blank=True
metadata | models.JSONField |  | blank=True
status | models.CharField |  | max_length=32; choices=STATUS_CHOICES; db_index=True
attempts | models.PositiveIntegerField |  | 
max_attempts | models.PositiveSmallIntegerField |  | 
last_attempt_at | models.DateTimeField |  | null=True; blank=True
next_retry_at | models.DateTimeField |  | null=True; blank=True; db_index=True
completed_at | models.DateTimeField |  | null=True; blank=True
last_error_code | models.CharField |  | max_length=80; blank=True
last_error | models.TextField |  | blank=True
created_at | models.DateTimeField |  | db_index=True
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-created_at']", "indexes": "[models.Index(fields=['integration', 'status', 'updated_at']), models.Index(fields=['source_model', 'source_id', 'created_at']), models.Index(fields=['request_id', 'created_at'])]"}`

## core/models.py::IntegrationCircuitState

[[F:core/models.py#7159-7186#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
integration | models.CharField |  | max_length=32; unique=True; db_index=True
status | models.CharField |  | max_length=16; choices=STATUS_CHOICES; db_index=True
consecutive_failures | models.PositiveIntegerField |  | 
failure_window_started_at | models.DateTimeField |  | null=True; blank=True
opened_at | models.DateTimeField |  | null=True; blank=True
next_probe_at | models.DateTimeField |  | null=True; blank=True
last_failure_code | models.CharField |  | max_length=80; blank=True
last_success_at | models.DateTimeField |  | null=True; blank=True
updated_at | models.DateTimeField |  | 

Model metadata: `{}`

## core/models.py::MiniAppDiagnosticSession

[[F:core/models.py#7189-7245#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
client_session_uuid | models.UUIDField |  | unique=True; db_index=True
actor | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.CASCADE; related_name='miniapp_diagnostic_sessions'
workflow | models.CharField |  | max_length=40; choices=AccessGrant.WORKFLOW_CHOICES; db_index=True
surface | models.CharField |  | max_length=40; db_index=True
release | models.CharField |  | max_length=80; blank=True; db_index=True
platform | models.CharField |  | max_length=16; db_index=True
network_bucket | models.CharField |  | max_length=16; db_index=True
device_memory_bucket | models.CharField |  | max_length=16; db_index=True
classification | models.CharField |  | max_length=40; choices=CLASSIFICATION_CHOICES; db_index=True
last_visibility | models.CharField |  | max_length=12
recovered_on_later_launch | models.BooleanField |  | db_index=True
started_at | models.DateTimeField |  | db_index=True
last_signal_at | models.DateTimeField |  | db_index=True
ended_at | models.DateTimeField |  | null=True; blank=True; db_index=True

Model metadata: `{"ordering": "['-started_at']", "indexes": "[models.Index(fields=['workflow', 'platform', 'started_at']), models.Index(fields=['classification', 'started_at'])]"}`

## core/models.py::MiniAppDiagnosticEvent

[[F:core/models.py#7248-7283#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
session | models.ForeignKey | MiniAppDiagnosticSession | on_delete=models.CASCADE; related_name='events'
client_event_uuid | models.UUIDField |  | 
event_type | models.CharField |  | max_length=40; db_index=True
elapsed_ms | models.PositiveIntegerField |  | 
route | models.CharField |  | max_length=80; blank=True
action | models.CharField |  | max_length=80; blank=True
visibility | models.CharField |  | max_length=12
online | models.BooleanField |  | 
network_bucket | models.CharField |  | max_length=16
status_bucket | models.CharField |  | max_length=24; blank=True
request_id | models.CharField |  | max_length=128; blank=True; db_index=True
recorded_at | models.DateTimeField |  | db_index=True

Model metadata: `{"ordering": "['session', 'elapsed_ms', 'recorded_at']", "constraints": "[models.UniqueConstraint(fields=['session', 'client_event_uuid'], name='unique_miniapp_diagnostic_client_event')]", "indexes": "[models.Index(fields=['session', 'recorded_at']), models.Index(fields=['event_type', 'recorded_at'])]"}`

## core/models.py::MiniAppDiagnosticDailyAggregate

[[F:core/models.py#7286-7314#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
date | models.DateField |  | db_index=True
workflow | models.CharField |  | max_length=40; db_index=True
surface | models.CharField |  | max_length=40; db_index=True
platform | models.CharField |  | max_length=16; db_index=True
release | models.CharField |  | max_length=80; blank=True; db_index=True
classification | models.CharField |  | max_length=40; db_index=True
network_bucket | models.CharField |  | max_length=16; db_index=True
session_count | models.PositiveIntegerField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-date', 'workflow', 'platform', 'classification']", "constraints": "[models.UniqueConstraint(fields=['date', 'workflow', 'surface', 'platform', 'release', 'classification', 'network_bucket'], name='unique_miniapp_diagnostic_daily_rollup')]"}`

## core/models.py::MiniAppLegacyWriteDailyAggregate

[[F:core/models.py#7317-7346#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
date | models.DateField |  | db_index=True
route_name | models.CharField |  | max_length=100; db_index=True
method | models.CharField |  | max_length=8
outcome | models.CharField |  | max_length=16; choices=OUTCOME_CHOICES; db_index=True
request_count | models.PositiveIntegerField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-date', 'route_name', 'method', 'outcome']", "constraints": "[models.UniqueConstraint(fields=['date', 'route_name', 'method', 'outcome'], name='unique_miniapp_legacy_write_daily_rollup')]"}`

## core/models.py::PublicEndpointThrottleBucket

[[F:core/models.py#7349-7373#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
scope | models.CharField |  | max_length=80
key_hash | models.CharField |  | max_length=64
window_started_at | models.DateTimeField |  | 
request_count | models.PositiveIntegerField |  | 
expires_at | models.DateTimeField |  | db_index=True
updated_at | models.DateTimeField |  | 

Model metadata: `{"constraints": "[models.UniqueConstraint(fields=['scope', 'key_hash', 'window_started_at'], name='unique_public_endpoint_throttle_window')]", "indexes": "[models.Index(fields=['scope', 'window_started_at'])]"}`

## core/models.py::ProductionReleaseAudit

[[F:core/models.py#7376-7416#13dc9e34]]

Field | Type | Relation | Options
--- | --- | --- | ---
release_id | models.CharField |  | max_length=160; primary_key=True
backup_reference | models.CharField |  | max_length=255
actor | models.CharField |  | max_length=160
environment | models.CharField |  | max_length=80
status | models.CharField |  | max_length=32; choices=STATUS_CHOICES
migration_names | models.JSONField |  | 
migration_plan_sha256 | models.CharField |  | max_length=64
readiness_results | models.JSONField |  | 
attempt_history | models.JSONField |  | 
post_migration_check_passed | models.BooleanField |  | 
superuser_bootstrap_result | models.CharField |  | max_length=32; blank=True
failure_code | models.CharField |  | max_length=80; blank=True
attempt_count | models.PositiveIntegerField |  | 
started_at | models.DateTimeField |  | 
migrations_completed_at | models.DateTimeField |  | blank=True; null=True
completed_at | models.DateTimeField |  | blank=True; null=True
updated_at | models.DateTimeField |  | 

Model metadata: `{"ordering": "['-started_at']"}`

## credit_assessments/models.py::CreditAssessment

[[F:credit_assessments/models.py#8-57#dc56726d]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
tat_case | models.OneToOneField | 'core.TatTrackerCase' | on_delete=models.PROTECT; related_name='credit_assessment'
state | models.CharField |  | max_length=32; choices=STATE_CHOICES; db_index=True
revision | models.PositiveBigIntegerField |  | 
statement_receipt | models.ForeignKey | 'StatementMailReceipt' | null=True; blank=True; on_delete=models.PROTECT; related_name='linked_assessments'
statement_period_start | models.DateField |  | null=True; blank=True
statement_period_end | models.DateField |  | null=True; blank=True
statement_full_year | models.BooleanField |  | null=True; blank=True
signed_laf_reference | models.CharField |  | max_length=255; blank=True
signed_laf_hash | models.CharField |  | max_length=64; blank=True
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'credit_assessment_case_root'", "indexes": "[models.Index(fields=['state', 'updated_at'], name='credit_assessment_state_idx')]"}`

## credit_assessments/models.py::StatementMailReceipt

[[F:credit_assessments/models.py#60-102#dc56726d]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
gmail_message_id | models.CharField |  | max_length=255
gmail_attachment_id | models.CharField |  | max_length=2048
gmail_thread_id | models.CharField |  | max_length=255; blank=True
forwarding_sender | models.EmailField |  | blank=True; db_index=True
subject | models.CharField |  | max_length=998; blank=True
original_sent_at | models.DateTimeField |  | null=True; blank=True
inbox_received_at | models.DateTimeField |  | db_index=True
original_time_source | models.CharField |  | max_length=32; blank=True
attachment_name | models.CharField |  | max_length=255
attachment_hash | models.CharField |  | max_length=64; db_index=True
attachment_size | models.PositiveBigIntegerField |  | 
masked_phone_pattern | models.CharField |  | max_length=32; blank=True
customer_name | models.CharField |  | max_length=255; blank=True
statement_metadata_source | models.CharField |  | max_length=32; blank=True
statement_period_start | models.DateField |  | null=True; blank=True
statement_period_end | models.DateField |  | null=True; blank=True
statement_full_year | models.BooleanField |  | null=True; blank=True
drive_file_id | models.CharField |  | max_length=255; blank=True
status | models.CharField |  | max_length=16; choices=STATUS_CHOICES; db_index=True
error_code | models.CharField |  | max_length=80; blank=True
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'credit_assessment_statement_receipt'", "constraints": "[models.UniqueConstraint(fields=['gmail_message_id', 'gmail_attachment_id'], name='unique_credit_mail_attachment')]", "indexes": "[models.Index(fields=['forwarding_sender', 'status', 'inbox_received_at'], name='credit_stmt_sender_status_idx'), models.Index(fields=['masked_phone_pattern', 'status'], name='credit_stmt_phone_status_idx')]"}`

## credit_assessments/models.py::MailboxCursor

[[F:credit_assessments/models.py#105-119#dc56726d]]

Field | Type | Relation | Options
--- | --- | --- | ---
singleton_key | models.CharField |  | max_length=32; primary_key=True
history_id | models.CharField |  | max_length=255; blank=True
last_polled_at | models.DateTimeField |  | null=True; blank=True
last_succeeded_at | models.DateTimeField |  | null=True; blank=True
last_error_code | models.CharField |  | max_length=80; blank=True
lease_owner | models.CharField |  | max_length=128; blank=True
lease_expires_at | models.DateTimeField |  | null=True; blank=True
updated_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'credit_assessment_mailbox_cursor'"}`

## credit_assessments/models.py::AssessmentDocument

[[F:credit_assessments/models.py#122-158#dc56726d]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
assessment | models.ForeignKey | CreditAssessment | on_delete=models.PROTECT; related_name='documents'
document_type | models.CharField |  | max_length=32; choices=TYPE_CHOICES; db_index=True
version | models.PositiveIntegerField |  | 
original_filename | models.CharField |  | max_length=255
mime_type | models.CharField |  | max_length=100
size | models.PositiveBigIntegerField |  | 
content_hash | models.CharField |  | max_length=64; db_index=True
drive_file_id | models.CharField |  | max_length=255; blank=True
source_reference | models.CharField |  | max_length=255; blank=True
is_current | models.BooleanField |  | db_index=True
uploaded_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'credit_assessment_document_evidence'", "constraints": "[models.UniqueConstraint(fields=['assessment', 'document_type', 'version'], name='unique_credit_document_version')]", "indexes": "[models.Index(fields=['assessment', 'document_type', 'is_current'], name='credit_document_current_idx')]"}`

## credit_assessments/models.py::AssessmentSecret

[[F:credit_assessments/models.py#161-172#dc56726d]]

Field | Type | Relation | Options
--- | --- | --- | ---
assessment | models.OneToOneField | CreditAssessment | on_delete=models.PROTECT; related_name='statement_secret'
ciphertext | models.TextField |  | 
key_version | models.CharField |  | max_length=32
reveal_count | models.PositiveIntegerField |  | 
last_revealed_at | models.DateTimeField |  | null=True; blank=True
destroyed_at | models.DateTimeField |  | null=True; blank=True
updated_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'credit_assessment_statement_secret'"}`

## credit_assessments/models.py::AnalysisPackage

[[F:credit_assessments/models.py#175-186#dc56726d]]

Field | Type | Relation | Options
--- | --- | --- | ---
assessment | models.ForeignKey | CreditAssessment | on_delete=models.PROTECT; related_name='analysis_packages'
revision | models.PositiveIntegerField |  | 
analysis_document | models.ForeignKey | AssessmentDocument | on_delete=models.PROTECT; related_name='analysis_packages'
submitted_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
content_digest | models.CharField |  | max_length=64; db_index=True
submitted_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'credit_assessment_analysis_package'", "constraints": "[models.UniqueConstraint(fields=['assessment', 'revision'], name='unique_credit_package_revision')]"}`

## credit_assessments/models.py::AnalysisQuestion

[[F:credit_assessments/models.py#189-204#dc56726d]]

Field | Type | Relation | Options
--- | --- | --- | ---
package | models.ForeignKey | AnalysisPackage | on_delete=models.PROTECT; related_name='questions'
sequence | models.PositiveIntegerField |  | 
text | models.TextField |  | 
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'credit_assessment_question_item'", "constraints": "[models.UniqueConstraint(fields=['package', 'sequence'], name='unique_credit_question_sequence')]"}`

## credit_assessments/models.py::QuestionResponse

[[F:credit_assessments/models.py#207-217#dc56726d]]

Field | Type | Relation | Options
--- | --- | --- | ---
question | models.ForeignKey | AnalysisQuestion | on_delete=models.PROTECT; related_name='responses'
revision | models.PositiveIntegerField |  | 
text | models.TextField |  | 
responded_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
responded_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'credit_assessment_question_response'", "constraints": "[models.UniqueConstraint(fields=['question', 'revision'], name='unique_credit_response_revision')]"}`

## credit_assessments/models.py::QuestionValidationEvent

[[F:credit_assessments/models.py#220-234#dc56726d]]

Field | Type | Relation | Options
--- | --- | --- | ---
response | models.ForeignKey | QuestionResponse | on_delete=models.PROTECT; related_name='validation_events'
outcome | models.CharField |  | max_length=16; choices=OUTCOME_CHOICES
comment | models.TextField |  | blank=True
validated_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
request_id | models.CharField |  | max_length=128; unique=True
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'credit_assessment_response_validation'"}`

## credit_assessments/models.py::AssessmentDecision

[[F:credit_assessments/models.py#237-260#dc56726d]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
assessment | models.ForeignKey | CreditAssessment | on_delete=models.PROTECT; related_name='decisions'
gate | models.CharField |  | max_length=20; choices=GATE_CHOICES; db_index=True
action | models.CharField |  | max_length=16; choices=ACTION_CHOICES
assessment_revision | models.PositiveBigIntegerField |  | 
package | models.ForeignKey | AnalysisPackage | null=True; blank=True; on_delete=models.PROTECT; related_name='decisions'
evidence_digest | models.CharField |  | max_length=64
comment | models.TextField |  | blank=True
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
request_id | models.CharField |  | max_length=128; unique=True
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'credit_assessment_manager_decision'"}`

## credit_assessments/models.py::AssessmentEvent

[[F:credit_assessments/models.py#263-276#dc56726d]]

Field | Type | Relation | Options
--- | --- | --- | ---
assessment | models.ForeignKey | CreditAssessment | on_delete=models.PROTECT; related_name='events'
action | models.CharField |  | max_length=64; db_index=True
revision | models.PositiveBigIntegerField |  | 
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
request_id | models.CharField |  | max_length=128; blank=True; db_index=True
metadata | models.JSONField |  | blank=True
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'credit_assessment_audit_event'", "ordering": "['created_at', 'pk']", "constraints": "[models.UniqueConstraint(fields=['assessment', 'request_id'], condition=~models.Q(request_id=''), name='unique_credit_assessment_request')]"}`

## credit_assessments/models.py::EngineJob

[[F:credit_assessments/models.py#279-299#dc56726d]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
assessment | models.ForeignKey | CreditAssessment | on_delete=models.PROTECT; related_name='engine_jobs'
assessment_revision | models.PositiveBigIntegerField |  | 
source_digest | models.CharField |  | max_length=64; db_index=True
contract_version | models.CharField |  | max_length=20
status | models.CharField |  | max_length=16; choices=STATUS_CHOICES; db_index=True
result | models.JSONField |  | blank=True
error_code | models.CharField |  | max_length=80; blank=True
created_at | models.DateTimeField |  | 
completed_at | models.DateTimeField |  | null=True; blank=True

Model metadata: `{"db_table": "'credit_assessment_engine_job'", "constraints": "[models.UniqueConstraint(fields=['assessment', 'assessment_revision', 'source_digest'], name='unique_credit_engine_source_revision')]"}`

## hb_operations/models.py::HomeBiogasAction

[[F:hb_operations/models.py#7-89#68267972]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
farmer | models.OneToOneField | 'core.JawabuFarmerMaster' | on_delete=models.PROTECT; related_name='homebiogas_action'
source_requisition_batch | models.ForeignKey | 'core.RequisitionBatch' | on_delete=models.PROTECT; related_name='homebiogas_actions'
source_signoff | models.ForeignKey | 'core.DocumentPhysicalSignoff' | on_delete=models.PROTECT; related_name='homebiogas_actions'
source_order_number | models.CharField |  | max_length=128
source_requisition_version | models.PositiveIntegerField |  | 
installation_status | models.CharField |  | max_length=32; choices=INSTALLATION_CHOICES
planned_installation_date | models.DateField |  | null=True; blank=True
installation_date | models.DateField |  | null=True; blank=True
serial_number | models.CharField |  | max_length=128; blank=True
readiness_status | models.CharField |  | max_length=24; choices=READINESS_CHOICES; blank=True
pending_installation_comment | models.TextField |  | blank=True
installation_report_status | models.CharField |  | max_length=24; choices=REPORT_CHOICES; blank=True
commissioning_status | models.CharField |  | max_length=24; choices=COMMISSIONING_CHOICES
commissioning_date | models.DateField |  | null=True; blank=True
pending_commissioning_comment | models.TextField |  | blank=True
cs_remarks | models.TextField |  | blank=True
revision | models.PositiveBigIntegerField |  | 
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
updated_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'hb_operations_action_root'", "ordering": "['-updated_at']", "indexes": "[models.Index(fields=['installation_status', 'updated_at'], name='hb_action_status_updated_idx')]"}`

## hb_operations/models.py::HomeBiogasActionEvent

[[F:hb_operations/models.py#92-116#68267972]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
action | models.ForeignKey | HomeBiogasAction | on_delete=models.PROTECT; related_name='events'
event_type | models.CharField |  | max_length=48
revision | models.PositiveBigIntegerField |  | 
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
actor_label | models.CharField |  | max_length=255; blank=True
request_id | models.CharField |  | max_length=128; blank=True
previous_values | models.JSONField |  | blank=True
new_values | models.JSONField |  | blank=True
reason | models.TextField |  | blank=True
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'hb_operations_action_event'", "ordering": "['created_at', 'pk']", "constraints": "[models.UniqueConstraint(fields=['action', 'request_id'], condition=~models.Q(request_id=''), name='unique_hb_action_request')]"}`

## origination/models.py::OriginationDataField

[[F:origination/models.py#11-264#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
key | models.SlugField |  | max_length=120; unique=True
label | models.CharField |  | max_length=160
aliases | models.JSONField |  | blank=True
category | models.CharField |  | max_length=80; blank=True
data_type | models.CharField |  | max_length=20; choices=TYPE_CHOICES
source_type | models.CharField |  | max_length=20; choices=SOURCE_CHOICES
sensitivity | models.CharField |  | max_length=20; choices=SENSITIVITY_CHOICES
masking_policy | models.CharField |  | max_length=16; choices=MASK_CHOICES
reporting_use | models.CharField |  | max_length=16; choices=REPORT_CHOICES
export_allowed | models.BooleanField |  | 
help_text | models.CharField |  | max_length=500; blank=True
choice_options | models.JSONField |  | blank=True
structure_schema | models.JSONField |  | blank=True
value_contract | models.JSONField |  | blank=True
active | models.BooleanField |  | db_index=True
preferred_field | models.ForeignKey | 'self' | null=True; blank=True; on_delete=models.PROTECT; related_name='legacy_equivalent_fields'
terminology_reviewed_distinct | models.BooleanField |  | 
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='created_origination_data_fields'
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'core_originationdatafield'", "ordering": "['category', 'label', 'key']", "indexes": "[models.Index(fields=['active', 'category', 'label'])]", "constraints": "[models.CheckConstraint(condition=models.Q(preferred_field__isnull=True) \| models.Q(active=False), name='orig_field_preferred_requires_inactive'), models.CheckConstraint(condition=models.Q(preferred_field__isnull=True) \| models.Q(terminology_reviewed_distinct=False), name='orig_field_preferred_not_distinct')]"}`

## origination/models.py::OriginationDataFieldEvent

[[F:origination/models.py#268-294#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
data_field | models.ForeignKey | OriginationDataField | on_delete=models.PROTECT; related_name='events'
action | models.CharField |  | max_length=40; db_index=True
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='origination_data_field_events'
metadata | models.JSONField |  | blank=True
occurred_at | models.DateTimeField |  | db_index=True

Model metadata: `{"db_table": "'core_originationdatafieldevent'", "ordering": "['occurred_at', 'id']"}`

## origination/models.py::OriginationProductDefinition

[[F:origination/models.py#298-386#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
product_version | models.ForeignKey | 'core.ProductVersion' | null=True; blank=True; on_delete=models.PROTECT; related_name='origination_definitions'
product_key | models.SlugField |  | max_length=80; db_index=True
name | models.CharField |  | max_length=160
version | models.PositiveIntegerField |  | 
form_schema | models.JSONField |  | 
signer_rules | models.JSONField |  | 
signing_policy | models.CharField |  | max_length=24; choices=[('legacy', 'Existing approval policy'), ('all_required', 'All required signers complete approval')]
signing_defaults | models.JSONField |  | blank=True
approval_roles | models.JSONField |  | blank=True
document_type | models.CharField |  | max_length=80
document_template_name | models.CharField |  | max_length=180; blank=True
document_template_version | models.PositiveIntegerField |  | 
document_template_sha256 | models.CharField |  | max_length=64; blank=True
is_active | models.BooleanField |  | db_index=True
lifecycle_status | models.CharField |  | max_length=16; choices=STATUS_CHOICES; db_index=True
supersedes | models.ForeignKey | 'self' | null=True; blank=True; on_delete=models.PROTECT; related_name='superseded_by_versions'
published_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='published_origination_product_definitions'
published_at | models.DateTimeField |  | null=True; blank=True
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='created_origination_product_definitions'
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'core_originationproductdefinition'", "ordering": "['product_key', '-version']", "constraints": "[models.UniqueConstraint(fields=['product_key', 'version'], name='unique_origination_product_version'), models.UniqueConstraint(fields=['product_key'], condition=models.Q(is_active=True), name='one_active_origination_product_version')]", "indexes": "[models.Index(fields=['product_key', 'is_active'], name='core_origin_product_67c040_idx')]"}`

## origination/models.py::OriginationProductDefinitionEvent

[[F:origination/models.py#390-416#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
product_definition | models.ForeignKey | OriginationProductDefinition | on_delete=models.PROTECT; related_name='events'
action | models.CharField |  | max_length=40; db_index=True
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='origination_product_definition_events'
metadata | models.JSONField |  | blank=True
occurred_at | models.DateTimeField |  | db_index=True

Model metadata: `{"db_table": "'core_originationproductdefinitionevent'", "ordering": "['occurred_at', 'id']"}`

## origination/models.py::OriginationFieldReviewIssue

[[F:origination/models.py#420-484#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
product_definition | models.ForeignKey | OriginationProductDefinition | on_delete=models.PROTECT; related_name='field_review_issues'
legacy_key | models.CharField |  | max_length=120
legacy_type | models.CharField |  | max_length=20; blank=True
legacy_label | models.CharField |  | max_length=160; blank=True
reason | models.CharField |  | max_length=80; blank=True
suggested_field | models.ForeignKey | OriginationDataField | null=True; blank=True; on_delete=models.PROTECT; related_name='suggested_legacy_reviews'
resolution_field | models.ForeignKey | OriginationDataField | null=True; blank=True; on_delete=models.PROTECT; related_name='resolved_legacy_reviews'
status | models.CharField |  | max_length=24; choices=STATUS_CHOICES; db_index=True
assigned_to | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='assigned_origination_field_reviews'
resolution_notes | models.TextField |  | blank=True
resolved_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='resolved_origination_field_reviews'
resolved_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'core_originationfieldreviewissue'", "ordering": "['status', '-created_at']", "constraints": "[models.UniqueConstraint(fields=['product_definition', 'legacy_key'], name='unique_origination_field_review_key')]", "indexes": "[models.Index(fields=['status', 'updated_at'])]"}`

## origination/models.py::OriginationDocumentTemplate

[[F:origination/models.py#488-618#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
product_definition | models.ForeignKey | OriginationProductDefinition | null=True; blank=True; on_delete=models.PROTECT; related_name='document_templates'
eligible_products | models.ManyToManyField | 'core.Product' | related_name='eligible_origination_document_templates'; blank=True
document_key | models.SlugField |  | max_length=80; db_index=True
document_role | models.CharField |  | max_length=16; choices=ROLE_CHOICES; db_index=True
inclusion_mode | models.CharField |  | max_length=24; choices=INCLUDE_CHOICES
display_order | models.PositiveSmallIntegerField |  | 
officer_selectable | models.BooleanField |  | 
default_selected | models.BooleanField |  | 
applicability_rule | models.JSONField |  | blank=True
form_schema | models.JSONField |  | blank=True
signer_rules | models.JSONField |  | blank=True
document_type | models.SlugField |  | max_length=80; db_index=True
name | models.CharField |  | max_length=180
version | models.PositiveIntegerField |  | 
status | models.CharField |  | max_length=24; choices=STATUS_CHOICES; db_index=True
source_filename | models.CharField |  | max_length=255
source_sha256 | models.CharField |  | max_length=64; db_index=True
source_byte_size | models.PositiveBigIntegerField |  | 
page_count | models.PositiveIntegerField |  | 
placement_config | models.JSONField |  | 
published_configuration_revision | models.ForeignKey | 'OriginationTemplateConfigurationRevision' | null=True; blank=True; on_delete=models.PROTECT; related_name='+'
native_consent_policy | models.ForeignKey | 'OriginationConsentPolicyVersion' | null=True; blank=True; on_delete=models.PROTECT; related_name='native_document_templates'
native_consent_attestation_reference | models.CharField |  | max_length=160; blank=True
native_consent_attested_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='attested_native_origination_consent_templates'
native_consent_attested_at | models.DateTimeField |  | null=True; blank=True
drive_file_id | models.CharField |  | max_length=255; blank=True
drive_url | models.URLField |  | max_length=1000; blank=True
upload_error | models.TextField |  | blank=True
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='created_origination_document_templates'
activated_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='activated_origination_document_templates'
activated_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'core_originationdocumenttemplate'", "ordering": "['product_definition', 'display_order', 'document_key', '-version']", "constraints": "[models.UniqueConstraint(fields=['document_type', 'version'], condition=models.Q(status__in=['ready', 'active']), name='unique_ready_active_orig_document_version'), models.UniqueConstraint(fields=['document_type'], condition=models.Q(status='active'), name='one_active_origination_document')]"}`

## origination/models.py::OriginationDocumentProductEligibility

[[F:origination/models.py#622-650#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
template | models.ForeignKey | OriginationDocumentTemplate | on_delete=models.PROTECT; related_name='product_eligibilities'
product | models.ForeignKey | 'core.Product' | on_delete=models.PROTECT; related_name='origination_document_eligibilities'
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='created_origination_document_eligibilities'
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'core_originationdocumentproducteligibility'", "ordering": "['template__document_type', 'product__name']", "constraints": "[models.UniqueConstraint(fields=['template', 'product'], name='unique_origination_document_product_eligibility')]"}`

## origination/models.py::OriginationProductDocumentAssignment

[[F:origination/models.py#654-764#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
product_definition | models.ForeignKey | OriginationProductDefinition | on_delete=models.PROTECT; related_name='document_assignments'
template | models.ForeignKey | OriginationDocumentTemplate | on_delete=models.PROTECT; related_name='product_assignments'
version_policy | models.CharField |  | max_length=24; choices=VERSION_POLICY_CHOICES
document_key | models.SlugField |  | max_length=80
name | models.CharField |  | max_length=180
display_order | models.PositiveSmallIntegerField |  | 
inclusion_mode | models.CharField |  | max_length=24; choices=OriginationDocumentTemplate.INCLUDE_CHOICES
officer_selectable | models.BooleanField |  | 
default_selected | models.BooleanField |  | 
applicability_rule | models.JSONField |  | blank=True
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='created_origination_document_assignments'
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'core_originationproductdocumentassignment'", "ordering": "['product_definition', 'display_order', 'document_key']", "constraints": "[models.UniqueConstraint(fields=['product_definition', 'document_key'], name='unique_origination_product_document_key'), models.UniqueConstraint(fields=['product_definition', 'template'], name='unique_origination_product_template_assignment')]"}`

## origination/models.py::OriginationDocumentTemplateEvent

[[F:origination/models.py#768-791#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
template | models.ForeignKey | OriginationDocumentTemplate | on_delete=models.PROTECT; related_name='events'
action | models.CharField |  | max_length=40; db_index=True
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='origination_document_template_events'
metadata | models.JSONField |  | blank=True
occurred_at | models.DateTimeField |  | db_index=True

Model metadata: `{"db_table": "'core_originationdocumenttemplateevent'", "ordering": "['occurred_at', 'id']"}`

## origination/models.py::OriginationTemplateConfigurationRevision

[[F:origination/models.py#795-825#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
template | models.ForeignKey | OriginationDocumentTemplate | on_delete=models.PROTECT; related_name='configuration_revisions'
revision | models.PositiveIntegerField |  | 
configuration | models.JSONField |  | 
is_published | models.BooleanField |  | db_index=True
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='origination_template_configuration_revisions'
created_at | models.DateTimeField |  | 
published_at | models.DateTimeField |  | null=True; blank=True

Model metadata: `{"db_table": "'core_originationtemplateconfigurationrevision'", "ordering": "['template', '-revision']", "constraints": "[models.UniqueConstraint(fields=['template', 'revision'], name='unique_origination_template_config_revision')]"}`

## origination/models.py::LoanOriginationApplication

[[F:origination/models.py#829-967#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
reference_number | models.CharField |  | max_length=80; unique=True; db_index=True
product_definition | models.ForeignKey | OriginationProductDefinition | on_delete=models.PROTECT; related_name='applications'
product_version | models.ForeignKey | 'core.ProductVersion' | null=True; blank=True; on_delete=models.PROTECT; related_name='origination_applications'
customer | models.ForeignKey | 'core.JawabuCustomer' | null=True; blank=True; on_delete=models.PROTECT; related_name='origination_applications'
officer | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='loan_origination_applications'
group_configuration | models.ForeignKey | 'core.GroupSheetConfiguration' | null=True; blank=True; on_delete=models.PROTECT; related_name='origination_applications'
branch | models.CharField |  | max_length=128; blank=True; db_index=True
branch_ref | models.ForeignKey | 'core.OperationalLocation' | null=True; blank=True; on_delete=models.PROTECT; related_name='origination_applications'
county_ref | models.ForeignKey | 'core.OperationalLocation' | null=True; blank=True; on_delete=models.PROTECT; related_name='origination_county_applications'
sub_county_ref | models.ForeignKey | 'core.OperationalLocation' | null=True; blank=True; on_delete=models.PROTECT; related_name='origination_sub_county_applications'
location_snapshot | models.JSONField |  | blank=True
status | models.CharField |  | max_length=32; choices=STATUS_CHOICES; db_index=True
revision | models.PositiveIntegerField |  | 
form_payload | models.JSONField |  | 
schema_snapshot | models.JSONField |  | 
signer_rules_snapshot | models.JSONField |  | 
signing_policy_snapshot | models.CharField |  | max_length=24
signing_plan | models.JSONField |  | blank=True
signing_plan_revision | models.PositiveIntegerField |  | 
approval_roles_snapshot | models.JSONField |  | blank=True
template_configuration_snapshot | models.JSONField |  | blank=True
primary_previewed_revision | models.PositiveIntegerField |  | null=True; blank=True
product_terms_snapshot | models.JSONField |  | blank=True
product_quote_snapshot | models.JSONField |  | blank=True
product_requirement_evidence | models.JSONField |  | blank=True
product_custom_values | models.JSONField |  | blank=True
product_selected_fee_keys | models.JSONField |  | blank=True
identity_snapshot | models.JSONField |  | blank=True
client_request_id | models.CharField |  | max_length=128; blank=True; db_index=True
creation_request_digest | models.CharField |  | max_length=64; blank=True; db_index=True
supersedes_application | models.ForeignKey | 'self' | null=True; blank=True; on_delete=models.PROTECT; related_name='replacement_applications'
reviewed_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='reviewed_loan_origination_applications'
recheck_assigned_to | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='assigned_origination_rechecks'
reviewed_at | models.DateTimeField |  | null=True; blank=True
final_reviewed_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='final_reviewed_loan_origination_applications'
final_reviewed_at | models.DateTimeField |  | null=True; blank=True
submitted_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | db_index=True
updated_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'core_loanoriginationapplication'", "ordering": "['-updated_at']", "constraints": "[models.UniqueConstraint(fields=['officer', 'client_request_id'], condition=~models.Q(client_request_id=''), name='unique_origination_create_request_per_officer')]", "indexes": "[models.Index(fields=['officer', 'status', 'updated_at'], name='core_loanor_officer_3c905e_idx'), models.Index(fields=['branch', 'status', 'updated_at'], name='core_loanor_branch_8c321c_idx')]"}`

## origination/models.py::OriginationCommercialException

[[F:origination/models.py#971-1048#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
application | models.ForeignKey | LoanOriginationApplication | on_delete=models.PROTECT; related_name='commercial_exceptions'
application_revision | models.PositiveIntegerField |  | 
product_version | models.ForeignKey | 'core.ProductVersion' | on_delete=models.PROTECT; related_name='origination_commercial_exceptions'
entered_terms_sha256 | models.CharField |  | max_length=64
expected_quote_sha256 | models.CharField |  | max_length=64
covered_mismatch_codes | models.JSONField |  | 
reason | models.TextField |  | 
approval_reference | models.CharField |  | max_length=255
approved_by | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='approved_origination_commercial_exceptions'
approved_at | models.DateTimeField |  | db_index=True

Model metadata: `{"db_table": "'core_originationcommercialexception'", "ordering": "['-approved_at', 'id']", "constraints": "[models.UniqueConstraint(fields=['application', 'application_revision', 'entered_terms_sha256', 'expected_quote_sha256'], name='unique_origination_commercial_exception')]", "indexes": "[models.Index(fields=['application', 'application_revision'], name='orig_comm_exception_rev_idx')]"}`

## origination/models.py::OriginationReportingValue

[[F:origination/models.py#1052-1137#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.BigAutoField |  | primary_key=True
application | models.ForeignKey | LoanOriginationApplication | on_delete=models.CASCADE; related_name='reporting_values'
data_field | models.ForeignKey | OriginationDataField | on_delete=models.PROTECT; related_name='reporting_values'
field_key | models.CharField |  | max_length=120
value_type | models.CharField |  | max_length=20; choices=OriginationDataField.TYPE_CHOICES
sensitivity | models.CharField |  | max_length=20; choices=OriginationDataField.SENSITIVITY_CHOICES
masking_policy | models.CharField |  | max_length=16; choices=OriginationDataField.MASK_CHOICES
reporting_use | models.CharField |  | max_length=16; choices=OriginationDataField.REPORT_CHOICES
export_allowed | models.BooleanField |  | 
text_value | models.CharField |  | max_length=500; null=True; blank=True
decimal_value | models.DecimalField |  | max_digits=24; decimal_places=4; null=True; blank=True
date_value | models.DateField |  | null=True; blank=True
boolean_value | models.BooleanField |  | null=True; blank=True
choice_code | models.CharField |  | max_length=120; null=True; blank=True
projected_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'core_originationreportingvalue'", "ordering": "['application', 'field_key']", "constraints": "[models.UniqueConstraint(fields=['application', 'data_field'], name='unique_origination_reporting_value'), models.CheckConstraint(condition=models.Q(value_type__in=['text', 'textarea', 'phone', 'national_id'], text_value__isnull=False, decimal_value__isnull=True, date_value__isnull=True, boolean_value__isnull=True, choice_code__isnull=True) \| models.Q(value_type__in=['number', 'money'], text_value__isnull=True, decimal_value__isnull=False, date_value__isnull=True, boolean_value__isnull=True, choice_code__isnull=True) \| models.Q(value_type='date', text_value__isnull=True, decimal_value__isnull=True, date_value__isnull=False, boolean_value__isnull=True, choice_code__isnull=True) \| models.Q(value_type='boolean', text_value__isnull=True, decimal_value__isnull=True, date_value__isnull=True, boolean_value__isnull=False, choice_code__isnull=True) \| models.Q(value_type='choice', text_value__isnull=True, decimal_value__isnull=True, date_value__isnull=True, boolean_value__isnull=True, choice_code__isnull=False), name='orig_reporting_matching_typed_value')]", "indexes": "[models.Index(fields=['data_field', 'text_value'], name='orig_report_field_text_idx'), models.Index(fields=['data_field', 'decimal_value'], name='orig_report_field_num_idx'), models.Index(fields=['data_field', 'date_value'], name='orig_report_field_date_idx'), models.Index(fields=['data_field', 'boolean_value'], name='orig_report_field_bool_idx'), models.Index(fields=['data_field', 'choice_code'], name='orig_report_field_choice_idx')]"}`

## origination/models.py::OriginationApplicationEvent

[[F:origination/models.py#1141-1180#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
application | models.ForeignKey | LoanOriginationApplication | on_delete=models.PROTECT; related_name='events'
action | models.CharField |  | max_length=80; db_index=True
revision | models.PositiveIntegerField |  | 
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='loan_origination_events'
request_id | models.CharField |  | max_length=128; blank=True; db_index=True
before_values | models.JSONField |  | blank=True
after_values | models.JSONField |  | blank=True
metadata | models.JSONField |  | blank=True
occurred_at | models.DateTimeField |  | db_index=True

Model metadata: `{"db_table": "'core_originationapplicationevent'", "ordering": "['occurred_at', 'id']", "indexes": "[models.Index(fields=['application', 'occurred_at'], name='core_origin_applica_ea7e72_idx')]", "constraints": "[models.UniqueConstraint(fields=['application', 'request_id'], condition=~models.Q(request_id=''), name='unique_origination_event_request')]"}`

## origination/models.py::OriginationReviewerNotice

[[F:origination/models.py#1184-1226#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
application | models.ForeignKey | LoanOriginationApplication | on_delete=models.PROTECT; related_name='reviewer_notices'
package | models.ForeignKey | 'OriginationSigningPackage' | null=True; blank=True; on_delete=models.PROTECT; related_name='reviewer_notices'
recipient | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='origination_reviewer_notices'
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='created_origination_reviewer_notices'
notice_type | models.CharField |  | max_length=32; choices=TYPE_CHOICES; db_index=True
message | models.CharField |  | max_length=500
request_id | models.CharField |  | max_length=128
seen_at | models.DateTimeField |  | null=True; blank=True; db_index=True
created_at | models.DateTimeField |  | db_index=True

Model metadata: `{"db_table": "'core_originationreviewernotice'", "ordering": "['-created_at']", "constraints": "[models.UniqueConstraint(fields=['application', 'recipient', 'request_id'], name='unique_orig_reviewer_notice_request')]"}`

## origination/models.py::OriginationCorrectionRequest

[[F:origination/models.py#1230-1280#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
application | models.ForeignKey | LoanOriginationApplication | on_delete=models.PROTECT; related_name='correction_requests'
application_revision | models.PositiveIntegerField |  | 
reviewer | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='origination_correction_requests'
summary | models.TextField |  | max_length=2000
status | models.CharField |  | max_length=16; choices=STATUS_CHOICES; db_index=True
addressed_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='addressed_origination_corrections'
addressed_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | db_index=True

Model metadata: `{"db_table": "'core_originationcorrectionrequest'", "ordering": "['-created_at']", "constraints": "[models.UniqueConstraint(fields=['application', 'application_revision'], name='unique_orig_correction_revision')]", "indexes": "[models.Index(fields=['application', 'status', 'created_at'], name='orig_corr_app_status_idx')]"}`

## origination/models.py::OriginationCorrectionItem

[[F:origination/models.py#1284-1323#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
correction_request | models.ForeignKey | OriginationCorrectionRequest | on_delete=models.PROTECT; related_name='items'
target_type | models.CharField |  | max_length=20; choices=TARGET_CHOICES
target_key | models.CharField |  | max_length=240
target_label | models.CharField |  | max_length=160
instruction | models.CharField |  | max_length=1000; blank=True
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'core_originationcorrectionitem'", "ordering": "['created_at', 'id']", "constraints": "[models.UniqueConstraint(fields=['correction_request', 'target_type', 'target_key'], name='unique_orig_correction_target')]"}`

## origination/models.py::OriginationRequirementEvidence

[[F:origination/models.py#1327-1393#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
application | models.ForeignKey | LoanOriginationApplication | on_delete=models.PROTECT; related_name='requirement_evidence_files'
application_revision | models.PositiveIntegerField |  | 
requirement_key | models.CharField |  | max_length=80
requirement_label | models.CharField |  | max_length=160
original_filename | models.CharField |  | max_length=255
mime_type | models.CharField |  | max_length=100
byte_size | models.PositiveBigIntegerField |  | 
content_sha256 | models.CharField |  | max_length=64; db_index=True
status | models.CharField |  | max_length=16; choices=STATUS_CHOICES; db_index=True
drive_file_id | models.CharField |  | max_length=255; blank=True
drive_url | models.URLField |  | max_length=1000; blank=True
upload_error | models.TextField |  | blank=True
request_id | models.CharField |  | max_length=128
uploaded_by | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='uploaded_origination_requirement_evidence'
removed_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='removed_origination_requirement_evidence'
removed_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | db_index=True
updated_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'core_originationrequirementevidence'", "ordering": "['requirement_key', '-created_at']", "constraints": "[models.UniqueConstraint(fields=['application', 'request_id'], name='unique_orig_evidence_request')]", "indexes": "[models.Index(fields=['application', 'requirement_key', 'status'], name='orig_evid_app_req_status_idx')]"}`

## origination/models.py::OriginationApplicationDocument

[[F:origination/models.py#1397-1449#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
application | models.ForeignKey | LoanOriginationApplication | on_delete=models.PROTECT; related_name='packet_documents'
template | models.ForeignKey | OriginationDocumentTemplate | null=True; blank=True; on_delete=models.PROTECT; related_name='application_documents'
assignment | models.ForeignKey | OriginationProductDocumentAssignment | null=True; blank=True; on_delete=models.PROTECT; related_name='application_documents'
document_key | models.SlugField |  | max_length=80
name | models.CharField |  | max_length=180
document_role | models.CharField |  | max_length=16; choices=OriginationDocumentTemplate.ROLE_CHOICES
display_order | models.PositiveSmallIntegerField |  | 
inclusion_mode | models.CharField |  | max_length=24; choices=OriginationDocumentTemplate.INCLUDE_CHOICES
selection_source | models.CharField |  | max_length=16; choices=SOURCE_CHOICES
applicable | models.BooleanField |  | 
selected | models.BooleanField |  | 
template_snapshot | models.JSONField |  | 
schema_snapshot | models.JSONField |  | blank=True
signer_rules_snapshot | models.JSONField |  | blank=True
field_payload | models.JSONField |  | blank=True
previewed_application_revision | models.PositiveIntegerField |  | null=True; blank=True
completed_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'core_originationapplicationdocument'", "ordering": "['display_order', 'document_key']", "constraints": "[models.UniqueConstraint(fields=['application', 'document_key'], name='unique_origination_application_document')]"}`

## origination/models.py::OriginationSigningParticipant

[[F:origination/models.py#1453-1483#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
application | models.ForeignKey | LoanOriginationApplication | on_delete=models.PROTECT; related_name='signing_participants'
role | models.CharField |  | max_length=80
participant_key | models.CharField |  | max_length=100
staff_user | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='assigned_origination_signing_participants'
configuration | models.JSONField |  | 
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='configured_origination_signing_participants'
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'origination_signing_participant_record'"}`

## origination/models.py::OriginationConsentPolicyVersion

[[F:origination/models.py#1486-1581#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
version | models.CharField |  | max_length=32; unique=True
status | models.CharField |  | max_length=16; choices=STATUS_CHOICES; db_index=True
packet_clause | models.TextField |  | 
signer_consent_text | models.TextField |  | 
signer_completion_text | models.TextField |  | 
resigning_text | models.TextField |  | 
approval_roles | models.JSONField |  | blank=True
signing_policy | models.CharField |  | max_length=24; choices=[('legacy', 'Existing approval policy'), ('all_required', 'All required signers complete approval')]
content_sha256 | models.CharField |  | max_length=64; unique=True
approval_reference | models.CharField |  | max_length=160
approved_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='approved_origination_consent_policies'
approved_at | models.DateTimeField |  | null=True; blank=True
retired_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='retired_origination_consent_policies'
retired_at | models.DateTimeField |  | null=True; blank=True
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='created_origination_consent_policies'
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'core_originationconsentpolicyversion'", "ordering": "['-created_at']", "constraints": "[models.UniqueConstraint(fields=['status', 'approval_roles', 'signing_policy'], condition=models.Q(status='active'), name='one_active_orig_consent_sequence')]"}`

## origination/models.py::OriginationSigningPackage

[[F:origination/models.py#1585-1689#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
application | models.ForeignKey | LoanOriginationApplication | on_delete=models.PROTECT; related_name='signing_packages'
application_revision | models.PositiveIntegerField |  | 
external_reference | models.CharField |  | max_length=80; unique=True; db_index=True
document_type | models.CharField |  | max_length=80
template_version | models.PositiveIntegerField |  | null=True; blank=True
template_sha256 | models.CharField |  | max_length=64; blank=True
template_configuration_snapshot | models.JSONField |  | blank=True
context_snapshot | models.JSONField |  | 
participants_snapshot | models.JSONField |  | 
requirement_evidence_snapshot | models.JSONField |  | blank=True
document_manifest_snapshot | models.JSONField |  | blank=True
combined_document_hash | models.CharField |  | max_length=64; blank=True
status | models.CharField |  | max_length=24; choices=STATUS_CHOICES; db_index=True
frozen_unsigned_document | models.BinaryField |  | blank=True
unsigned_document_hash | models.CharField |  | max_length=64; blank=True
review_scope_sha256 | models.CharField |  | max_length=64; blank=True; db_index=True
conditional_approval | models.BooleanField |  | db_index=True
consent_policy | models.ForeignKey | OriginationConsentPolicyVersion | null=True; blank=True; on_delete=models.PROTECT; related_name='signing_packages'
consent_policy_snapshot | models.JSONField |  | blank=True
approved_unsigned_document_hash | models.CharField |  | max_length=64; blank=True
approved_review_scope_sha256 | models.CharField |  | max_length=64; blank=True
prepared_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='prepared_origination_review_packages'
prepared_at | models.DateTimeField |  | null=True; blank=True
reviewed_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='reviewed_origination_signing_packages'
reviewed_at | models.DateTimeField |  | null=True; blank=True
final_reviewed_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='final_reviewed_origination_signing_packages'
final_reviewed_at | models.DateTimeField |  | null=True; blank=True
final_decision | models.CharField |  | max_length=24; blank=True
final_review_reason | models.TextField |  | blank=True
final_approved_signed_document_hash | models.CharField |  | max_length=64; blank=True
signed_document_hash | models.CharField |  | max_length=64; blank=True
final_document_reference | models.TextField |  | blank=True
final_drive_file_id | models.CharField |  | max_length=255; blank=True
archive_status | models.CharField |  | max_length=24; choices=[('not_ready', 'Not ready'), ('pending', 'Pending'), ('uploaded', 'Uploaded'), ('failed', 'Failed')]; db_index=True
archive_error | models.TextField |  | blank=True
pending_signed_document | models.BinaryField |  | blank=True
finalized_at | models.DateTimeField |  | null=True; blank=True
archived_at | models.DateTimeField |  | null=True; blank=True
remote_error | models.TextField |  | blank=True
test_mode | models.BooleanField |  | 
test_completed_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'core_originationsigningpackage'", "ordering": "['-created_at']", "constraints": "[models.UniqueConstraint(fields=['application', 'application_revision'], name='one_signing_package_per_origination_revision')]", "indexes": "[models.Index(fields=['application', 'status', 'updated_at'], name='core_origin_applica_3a6bd3_idx')]"}`

## origination/models.py::OriginationStampAsset

[[F:origination/models.py#1693-1742#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
name | models.CharField |  | max_length=160
branch | models.ForeignKey | 'core.OperationalLocation' | null=True; blank=True; on_delete=models.PROTECT; related_name='origination_stamp_assets'
environment | models.CharField |  | max_length=16; choices=ENV_CHOICES
version | models.PositiveIntegerField |  | 
image_png | models.BinaryField |  | 
content_sha256 | models.CharField |  | max_length=64; db_index=True
byte_size | models.PositiveIntegerField |  | 
active | models.BooleanField |  | db_index=True
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='created_origination_stamp_assets'
activated_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='activated_origination_stamp_assets'
activated_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'core_originationstampasset'", "ordering": "['name', 'branch', '-version']", "constraints": "[models.UniqueConstraint(fields=['name', 'environment', 'version'], condition=models.Q(branch__isnull=True), name='unique_global_origination_stamp_version'), models.UniqueConstraint(fields=['name', 'branch', 'environment', 'version'], condition=models.Q(branch__isnull=False), name='unique_branch_origination_stamp_version')]"}`

## origination/models.py::OriginationSignerSession

[[F:origination/models.py#1746-1846#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
participant | models.ForeignKey | OriginationSigningParticipant | null=True; blank=True; on_delete=models.PROTECT; related_name='signer_sessions'
id | models.UUIDField |  | primary_key=True
package | models.ForeignKey | OriginationSigningPackage | on_delete=models.PROTECT; related_name='signer_sessions'
signer_role | models.CharField |  | max_length=80
sms_provider | models.CharField |  | max_length=32; choices=[('africas_talking', "Africa's Talking"), ('advanta', 'Advanta')]
identity_snapshot | models.JSONField |  | blank=True
phone_normalized | models.CharField |  | max_length=16; blank=True
phone_hash | models.CharField |  | max_length=64; blank=True; db_index=True
phone_last4 | models.CharField |  | max_length=4; blank=True
token_hash | models.CharField |  | max_length=64; unique=True; db_index=True
token_expires_at | models.DateTimeField |  | db_index=True
status | models.CharField |  | max_length=24; choices=STATUS_CHOICES; db_index=True
access_mode | models.CharField |  | max_length=24; choices=MODE_CHOICES
is_active | models.BooleanField |  | db_index=True
consent_version | models.CharField |  | max_length=32; blank=True
consented_at | models.DateTimeField |  | null=True; blank=True
reviewed_pages | models.JSONField |  | blank=True
signature_capture | models.JSONField |  | blank=True
signature_capture_sha256 | models.CharField |  | max_length=64; blank=True
verified_at | models.DateTimeField |  | null=True; blank=True
locked_until | models.DateTimeField |  | null=True; blank=True
invalidated_at | models.DateTimeField |  | null=True; blank=True
shared_phone_override_reason | models.TextField |  | blank=True
shared_phone_approved_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='approved_origination_shared_phone_sessions'
shared_phone_approved_at | models.DateTimeField |  | null=True; blank=True
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='created_origination_signer_sessions'
assisted_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='assisted_origination_signer_sessions'
request_id | models.CharField |  | max_length=128; blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'core_originationsignersession'", "ordering": "['package', 'signer_role', '-created_at']", "constraints": "[models.UniqueConstraint(fields=['package', 'signer_role'], condition=models.Q(is_active=True, participant__isnull=True), name='one_active_origination_signer_session'), models.UniqueConstraint(fields=['package', 'participant'], condition=models.Q(is_active=True, participant__isnull=False), name='one_active_orig_participant_session'), models.UniqueConstraint(fields=['package', 'request_id'], condition=~models.Q(request_id=''), name='unique_origination_signer_session_request')]"}`

## origination/models.py::OriginationOtpChallenge

[[F:origination/models.py#1850-1901#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
session | models.ForeignKey | OriginationSignerSession | on_delete=models.PROTECT; related_name='otp_challenges'
code_hash | models.CharField |  | max_length=255
binding_sha256 | models.CharField |  | max_length=64
provider_message_id | models.CharField |  | max_length=255; blank=True; db_index=True
delivery_status | models.CharField |  | max_length=24; choices=DELIVERY_CHOICES; db_index=True
provider_status | models.CharField |  | max_length=80; blank=True
send_sequence | models.PositiveSmallIntegerField |  | 
attempts_remaining | models.PositiveSmallIntegerField |  | 
request_id | models.CharField |  | max_length=128
source_ip_hash | models.CharField |  | max_length=64; blank=True; db_index=True
expires_at | models.DateTimeField |  | db_index=True
verified_at | models.DateTimeField |  | null=True; blank=True
invalidated_at | models.DateTimeField |  | null=True; blank=True
last_attempt_at | models.DateTimeField |  | null=True; blank=True
created_at | models.DateTimeField |  | db_index=True

Model metadata: `{"db_table": "'core_originationotpchallenge'", "ordering": "['session', '-send_sequence']", "constraints": "[models.UniqueConstraint(fields=['session', 'send_sequence'], name='unique_origination_otp_sequence'), models.UniqueConstraint(fields=['session', 'request_id'], name='unique_origination_otp_request')]"}`

## origination/models.py::OriginationSigningRequestEvent

[[F:origination/models.py#1905-1940#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.BigAutoField |  | primary_key=True
session | models.ForeignKey | OriginationSignerSession | null=True; blank=True; on_delete=models.CASCADE; related_name='request_events'
action | models.CharField |  | max_length=16; choices=ACTION_CHOICES; db_index=True
request_id | models.CharField |  | max_length=128; blank=True
payload_digest | models.CharField |  | max_length=64; blank=True
token_hash | models.CharField |  | max_length=64; blank=True; db_index=True
source_ip_hash | models.CharField |  | max_length=64; blank=True; db_index=True
created_at | models.DateTimeField |  | db_index=True

Model metadata: `{"db_table": "'core_originationsigningrequestevent'", "ordering": "['-created_at']", "indexes": "[models.Index(fields=['action', 'token_hash', 'created_at'], name='core_osre_token_created_idx'), models.Index(fields=['action', 'source_ip_hash', 'created_at'], name='core_osre_ip_created_idx')]", "constraints": "[models.UniqueConstraint(fields=['session', 'action', 'request_id'], condition=~models.Q(request_id=''), name='unique_origination_signing_request_event')]"}`

## origination/models.py::OriginationSigningAction

[[F:origination/models.py#1944-2007#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
participant | models.ForeignKey | OriginationSigningParticipant | null=True; blank=True; on_delete=models.PROTECT; related_name='signing_actions'
id | models.UUIDField |  | primary_key=True
package | models.ForeignKey | OriginationSigningPackage | on_delete=models.PROTECT; related_name='actions'
document_key | models.SlugField |  | max_length=80
slot_key | models.SlugField |  | max_length=80
signer_role | models.CharField |  | max_length=80
action_type | models.CharField |  | max_length=16; choices=TYPE_CHOICES
mode | models.CharField |  | max_length=16; choices=MODE_CHOICES
stamp_asset | models.ForeignKey | OriginationStampAsset | null=True; blank=True; on_delete=models.PROTECT; related_name='signing_actions'
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.PROTECT; related_name='origination_signing_actions'
signer_session | models.ForeignKey | OriginationSignerSession | null=True; blank=True; on_delete=models.PROTECT; related_name='actions'
supersedes | models.OneToOneField | 'self' | null=True; blank=True; on_delete=models.PROTECT; related_name='superseded_by'
request_id | models.CharField |  | max_length=128; db_index=True
metadata | models.JSONField |  | blank=True
created_at | models.DateTimeField |  | db_index=True

Model metadata: `{"db_table": "'core_originationsigningaction'", "ordering": "['created_at', 'id']", "constraints": "[models.UniqueConstraint(fields=['package', 'request_id'], name='unique_origination_signing_action_request')]"}`

## origination/models.py::OriginationSigningActionInvalidation

[[F:origination/models.py#2011-2037#51088e88]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
action | models.OneToOneField | OriginationSigningAction | on_delete=models.PROTECT; related_name='invalidation'
reason | models.CharField |  | max_length=1000
invalidated_by | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.PROTECT; related_name='invalidated_origination_signing_actions'
request_id | models.CharField |  | max_length=128; unique=True
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'core_originationsigningactioninvalidation'"}`

## payments/models.py::InvoiceNameAgreement

[[F:payments/models.py#7-28#d9fba937]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
artifact | models.OneToOneField | 'core.InvoiceNameChangeLetterArtifact' | on_delete=models.PROTECT; related_name='signed_agreement'
filename | models.CharField |  | max_length=255
content_type | models.CharField |  | max_length=100
file_content | models.BinaryField |  | 
checksum | models.CharField |  | max_length=64
identity_facts | models.JSONField |  | 
accepted_by | models.CharField |  | max_length=255
accepted_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'payment_invoice_name_agreement'"}`

## payments/models.py::PaymentSequenceState

[[F:payments/models.py#31-51#d9fba937]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.BigAutoField |  | primary_key=True
group_configuration | models.OneToOneField | 'core.GroupSheetConfiguration' | on_delete=models.PROTECT; related_name='payment_sequence'
next_number | models.PositiveBigIntegerField |  | 
revision | models.PositiveBigIntegerField |  | 
updated_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
adjustment_reason | models.TextField |  | blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'payment_sequence_state'"}`

## payments/models.py::PaymentNumberClaim

[[F:payments/models.py#54-65#d9fba937]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.BigAutoField |  | primary_key=True
sequence | models.ForeignKey | PaymentSequenceState | on_delete=models.PROTECT; related_name='number_claims'
number | models.PositiveBigIntegerField |  | 
batch | models.OneToOneField | 'PaymentBatch' | null=True; blank=True; on_delete=models.PROTECT; related_name='number_claim'
retired | models.BooleanField |  | 

Model metadata: `{"db_table": "'payment_number_claim'", "constraints": "[models.UniqueConstraint(fields=['sequence', 'number'], name='unique_payment_number_claim')]"}`

## payments/models.py::PaymentBatch

[[F:payments/models.py#68-121#d9fba937]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
group_configuration | models.ForeignKey | 'core.GroupSheetConfiguration' | on_delete=models.PROTECT; related_name='payment_batches'
payment_number | models.PositiveBigIntegerField |  | null=True; blank=True
status | models.CharField |  | max_length=24; choices=STATUS_CHOICES; db_index=True
revision | models.PositiveBigIntegerField |  | 
batch_digest | models.CharField |  | max_length=64; blank=True
current_document | models.ForeignKey | 'core.PaymentDocument' | null=True; blank=True; on_delete=models.PROTECT; related_name='governed_payment_batches'
receipt_batch | models.OneToOneField | 'PaymentReceiptBatch' | null=True; blank=True; on_delete=models.PROTECT; related_name='payment_batch'
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
submitted_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
confirmed_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
completed_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
submitted_at | models.DateTimeField |  | null=True; blank=True
confirmed_at | models.DateTimeField |  | null=True; blank=True
completed_at | models.DateTimeField |  | null=True; blank=True
cancellation_reason | models.TextField |  | blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'payment_batch'", "ordering": "['-created_at']", "constraints": "[models.UniqueConstraint(fields=['group_configuration', 'payment_number'], condition=models.Q(payment_number__isnull=False) & ~models.Q(status='cancelled'), name='unique_group_payment_number')]", "indexes": "[models.Index(fields=['group_configuration', 'status'], name='payment_batch_group_status_idx')]"}`

## payments/models.py::PaymentReceiptBatch

[[F:payments/models.py#124-162#d9fba937]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
group_configuration | models.ForeignKey | 'core.GroupSheetConfiguration' | on_delete=models.PROTECT; related_name='payment_receipt_batches'
status | models.CharField |  | max_length=24; choices=STATUS_CHOICES; db_index=True
revision | models.PositiveBigIntegerField |  | 
archived_at | models.DateTimeField |  | null=True; blank=True
archived_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
request_id | models.CharField |  | max_length=128; blank=True; db_index=True
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'payment_receipt_batch'", "ordering": "['-created_at']", "constraints": "[models.UniqueConstraint(fields=['request_id'], condition=~models.Q(request_id=''), name='payment_receipt_batch_request_unique')]", "indexes": "[models.Index(fields=['group_configuration', 'status'], name='payrcpt_group_status_idx')]"}`

## payments/models.py::PaymentReceiptItem

[[F:payments/models.py#165-198#d9fba937]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
receipt_batch | models.ForeignKey | PaymentReceiptBatch | on_delete=models.PROTECT; related_name='items'
invoice | models.OneToOneField | 'core.ParsedInvoice' | null=True; blank=True; on_delete=models.PROTECT; related_name='payment_receipt_item'
source_upload | models.ForeignKey | 'core.InvoiceUploadBatch' | on_delete=models.PROTECT; related_name='payment_receipt_items'
farmer | models.ForeignKey | 'core.JawabuFarmerMaster' | null=True; blank=True; on_delete=models.PROTECT; related_name='payment_receipt_items'
status | models.CharField |  | max_length=24; choices=STATUS_CHOICES; db_index=True
reason | models.TextField |  | blank=True
replacement_invoice | models.ForeignKey | 'core.ParsedInvoice' | null=True; blank=True; on_delete=models.PROTECT; related_name='+'
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'payment_receipt_item'", "constraints": "[models.UniqueConstraint(fields=['receipt_batch', 'source_upload', 'invoice'], name='payment_receipt_item_source_invoice_unique')]", "indexes": "[models.Index(fields=['receipt_batch', 'status'], name='payrcpt_item_batch_status_idx')]"}`

## payments/models.py::PaymentBatchCase

[[F:payments/models.py#201-231#d9fba937]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
batch | models.ForeignKey | PaymentBatch | on_delete=models.PROTECT; related_name='case_memberships'
farmer | models.ForeignKey | 'core.JawabuFarmerMaster' | on_delete=models.PROTECT; related_name='payment_batch_memberships'
payment_mode | models.CharField |  | max_length=20; choices=MODE_CHOICES
is_active | models.BooleanField |  | db_index=True
case_digest | models.CharField |  | max_length=64
added_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
removed_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
removed_reason | models.TextField |  | blank=True
added_at | models.DateTimeField |  | 
removed_at | models.DateTimeField |  | null=True; blank=True
updated_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'payment_batch_case'", "constraints": "[models.UniqueConstraint(fields=['batch', 'farmer'], name='unique_payment_batch_case'), models.CheckConstraint(condition=models.Q(payment_mode__in=['LOAN-JAWABU', 'CASH']), name='payment_batch_case_mode_valid')]", "indexes": "[models.Index(fields=['batch', 'is_active'], name='payment_batch_case_active_idx')]"}`

## payments/models.py::PaymentCaseReview

[[F:payments/models.py#234-257#d9fba937]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.BigAutoField |  | primary_key=True
membership | models.OneToOneField | PaymentBatchCase | on_delete=models.PROTECT; related_name='review'
decision | models.CharField |  | max_length=16; choices=DECISION_CHOICES; db_index=True
comment | models.TextField |  | blank=True
reviewed_digest | models.CharField |  | max_length=64; blank=True
reviewed_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
reviewed_at | models.DateTimeField |  | null=True; blank=True
revision | models.PositiveBigIntegerField |  | 
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'payment_case_review'"}`

## payments/models.py::PaymentSequenceEvent

[[F:payments/models.py#260-276#d9fba937]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.BigAutoField |  | primary_key=True
sequence | models.ForeignKey | PaymentSequenceState | on_delete=models.PROTECT; related_name='events'
batch | models.ForeignKey | PaymentBatch | null=True; blank=True; on_delete=models.PROTECT; related_name='sequence_events'
action | models.CharField |  | max_length=24
number_before | models.PositiveBigIntegerField |  | 
number_after | models.PositiveBigIntegerField |  | 
revision_after | models.PositiveBigIntegerField |  | 
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
reason | models.TextField |  | 
request_id | models.CharField |  | max_length=128; blank=True; db_index=True
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'payment_sequence_event'", "constraints": "[models.UniqueConstraint(fields=['request_id'], condition=~models.Q(request_id=''), name='unique_payment_sequence_request')]"}`

## payments/models.py::PaymentBatchEvent

[[F:payments/models.py#279-293#d9fba937]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.BigAutoField |  | primary_key=True
batch | models.ForeignKey | PaymentBatch | on_delete=models.PROTECT; related_name='events'
action | models.CharField |  | max_length=40
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
request_id | models.CharField |  | max_length=128; blank=True; db_index=True
revision | models.PositiveBigIntegerField |  | 
metadata | models.JSONField |  | blank=True
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'payment_batch_event'", "ordering": "['created_at', 'pk']", "constraints": "[models.UniqueConstraint(fields=['request_id'], condition=~models.Q(request_id=''), name='unique_payment_batch_event_request')]"}`

## portal_recognition/models.py::PortalRecognitionPeriodSnapshot

[[F:portal_recognition/models.py#5-27#4f6afd34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.BigAutoField |  | primary_key=True
group_configuration_id | models.BigIntegerField |  | 
period_kind | models.CharField |  | max_length=8
period_key | models.CharField |  | max_length=12
score_policy_version | models.PositiveSmallIntegerField |  | 
facts | models.JSONField |  | 
captured_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'portal_recognition_period_snapshot'", "constraints": "[models.UniqueConstraint(fields=['group_configuration_id', 'period_kind', 'period_key', 'score_policy_version'], name='unique_portal_recognition_versioned_period')]"}`

## portal_recognition/models.py::PortalRecognitionLiveStanding

[[F:portal_recognition/models.py#30-46#4f6afd34]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.BigAutoField |  | primary_key=True
viewer | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.CASCADE; related_name='+'
context_key | models.CharField |  | max_length=64; unique=True
group_configuration_ids | models.JSONField |  | 
ranks | models.JSONField |  | 
signature | models.CharField |  | max_length=64; blank=True
movement | models.JSONField |  | 
observed_at | models.DateTimeField |  | 
expires_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'portal_recognition_live_standing'", "indexes": "[models.Index(fields=['expires_at'], name='portal_live_expiry_idx')]"}`

## qa_tracker/models.py::TestCase

[[F:qa_tracker/models.py#7-27#73a1e8a7]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.CharField |  | max_length=32; primary_key=True
app | models.CharField |  | max_length=32
journey | models.CharField |  | max_length=100
description | models.CharField |  | max_length=255
steps | models.TextField |  | 
expected | models.TextField |  | 
priority | models.CharField |  | max_length=12; choices=[('high', 'High'), ('normal', 'Normal'), ('low', 'Low')]
automation_gap | models.BooleanField |  | 
active | models.BooleanField |  | 
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'qa_tracker_test_case_root'", "ordering": "['app', 'journey', 'id']"}`

## qa_tracker/models.py::TestCycle

[[F:qa_tracker/models.py#30-57#73a1e8a7]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
app | models.CharField |  | max_length=32; choices=[('portal', 'Portal'), ('tat_tracker', 'TAT Tracker'), ('complaints', 'Complaints'), ('spin', 'SPIN'), ('origination', 'Origination'), ('fca_review', 'FCA Review'), ('farmers_review', 'Farmers Review'), ('order_approval', 'Order Approval')]
release | models.CharField |  | max_length=80
environment | models.CharField |  | max_length=24; choices=[('pilot', 'Pilot'), ('staging', 'Staging'), ('production', 'Production')]
build_commit | models.CharField |  | max_length=40; blank=True
group_configuration | models.ForeignKey | 'core.GroupSheetConfiguration' | on_delete=models.PROTECT; related_name='qa_test_cycles'
branch | models.CharField |  | max_length=120; blank=True
product | models.CharField |  | max_length=120; blank=True
case_ids | models.JSONField |  | blank=True
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; on_delete=models.SET_NULL; related_name='+'
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'qa_tracker_test_cycle_root'", "ordering": "['-created_at']", "constraints": "[models.UniqueConstraint(fields=['app', 'release', 'environment', 'group_configuration', 'branch', 'product'], name='qa_cycle_unique_scope_release')]"}`

## qa_tracker/models.py::TestRun

[[F:qa_tracker/models.py#60-82#73a1e8a7]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
cycle | models.ForeignKey | TestCycle | on_delete=models.PROTECT; related_name='runs'
test_case | models.ForeignKey | TestCase | on_delete=models.PROTECT; related_name='runs'
test_description | models.CharField |  | max_length=255
test_steps | models.TextField |  | 
test_expected | models.TextField |  | 
tester | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; on_delete=models.SET_NULL; related_name='+'
result | models.CharField |  | max_length=12; choices=RESULT_CHOICES
severity | models.CharField |  | max_length=12; choices=[('blocker', 'Blocker'), ('major', 'Major'), ('minor', 'Minor')]; blank=True
bug_reference | models.CharField |  | max_length=100; blank=True
notes | models.TextField |  | blank=True
request_key | models.UUIDField |  | unique=True
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'qa_tracker_test_run_event'", "ordering": "['-created_at', '-id']", "indexes": "[models.Index(fields=['cycle', 'test_case', '-created_at'], name='qa_run_cycle_case_time_idx')]"}`

## qa_tracker/models.py::TestEvidence

[[F:qa_tracker/models.py#85-100#73a1e8a7]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
run | models.ForeignKey | TestRun | on_delete=models.PROTECT; related_name='evidence'
drive_file_id | models.CharField |  | max_length=255
filename | models.CharField |  | max_length=180
mime_type | models.CharField |  | max_length=32
size_bytes | models.PositiveIntegerField |  | 
sha256 | models.CharField |  | max_length=64
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'qa_tracker_test_evidence_link'", "constraints": "[models.UniqueConstraint(fields=['run', 'sha256'], name='qa_evidence_unique_run_hash')]"}`

## report_delivery/models.py::ScopedConfiguration

[[F:report_delivery/models.py#10-21#4d25bf3e]]

Field | Type | Relation | Options
--- | --- | --- | ---
workflow | models.CharField |  | max_length=24; choices=[('jawabu_portal', 'Portal'), ('tat_tracker', 'TAT'), ('complaint_cases', 'Complaints')]
id | models.UUIDField |  | primary_key=True
group_configuration | models.ForeignKey | 'core.GroupSheetConfiguration' | on_delete=models.PROTECT; related_name='%(class)s_report_configurations'
branch | models.CharField |  | max_length=120; blank=True
product | models.CharField |  | max_length=120; blank=True
authorized_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; on_delete=models.SET_NULL; related_name='authorized_%(class)s_reports'
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"abstract": "True"}`

## report_delivery/models.py::ApprovedRecipient

[[F:report_delivery/models.py#24-37#4d25bf3e]]

Field | Type | Relation | Options
--- | --- | --- | ---
email | models.EmailField |  | 
active | models.BooleanField |  | 
suppressed | models.BooleanField |  | 
suppression_reason | models.CharField |  | max_length=40; blank=True

Model metadata: `{"db_table": "'report_delivery_recipient_root'", "constraints": "[models.UniqueConstraint(fields=['workflow', 'group_configuration', 'email', 'branch', 'product'], name='report_recipient_scope_unique')]", "ordering": "['email']"}`

## report_delivery/models.py::ReportSchedule

[[F:report_delivery/models.py#40-62#4d25bf3e]]

Field | Type | Relation | Options
--- | --- | --- | ---
title | models.CharField |  | max_length=100
preset | models.CharField |  | max_length=12; choices=[('pipeline', 'Pipeline'), ('outcomes', 'Outcomes'), ('finance', 'Finance'), ('tat', 'Tat'), ('complaints', 'Summary'), ('cmp_tat', 'Turnaround performance'), ('cmp_open', 'Open-case follow-up')]
county | models.CharField |  | max_length=120; blank=True
recipients | models.ManyToManyField | ApprovedRecipient | related_name='schedules'
frequency | models.CharField |  | max_length=12; choices=[(v, v.title()) for v in ('daily', 'weekly', 'monthly', 'quarterly', 'yearly')]
send_time | models.TimeField |  | 
active | models.BooleanField |  | 
skip_empty | models.BooleanField |  | 
revision | models.PositiveIntegerField |  | 
next_run_at | models.DateTimeField |  | null=True; blank=True
skipped_occurrences | models.PositiveIntegerField |  | 

Model metadata: `{"db_table": "'report_delivery_schedule_root'", "ordering": "['title']"}`

## report_delivery/models.py::ScheduleRecipient

[[F:report_delivery/models.py#65-72#4d25bf3e]]

Field | Type | Relation | Options
--- | --- | --- | ---
schedule | models.ForeignKey | ReportSchedule | on_delete=models.CASCADE; related_name='recipient_links'
recipient | models.ForeignKey | ApprovedRecipient | on_delete=models.PROTECT; related_name='schedule_links'

Model metadata: `{"db_table": "'report_delivery_recipient_link'", "constraints": "[models.UniqueConstraint(fields=['schedule', 'recipient'], name='report_schedule_recipient_unique')]"}`

## report_delivery/models.py::ReportDelivery

[[F:report_delivery/models.py#75-123#4d25bf3e]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
schedule | models.ForeignKey | ReportSchedule | null=True; blank=True; on_delete=models.PROTECT; related_name='deliveries'
recipient | models.ForeignKey | ApprovedRecipient | null=True; blank=True; on_delete=models.PROTECT; related_name='deliveries'
requested_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='requested_report_deliveries'
destination | models.EmailField |  | blank=True
occurrence | models.CharField |  | max_length=100
configuration | models.JSONField |  | 
status | models.CharField |  | max_length=12; choices=STATUSES
payload | models.JSONField |  | 
payload_hash | models.CharField |  | max_length=64; blank=True
snapshot | models.JSONField |  | 
provider_id | models.CharField |  | max_length=100; blank=True
attempts | models.PositiveSmallIntegerField |  | 
first_attempt_at | models.DateTimeField |  | null=True
next_attempt_at | models.DateTimeField |  | 
lease_token | models.UUIDField |  | null=True
lease_until | models.DateTimeField |  | null=True
error_code | models.CharField |  | max_length=60; blank=True
last_event_at | models.DateTimeField |  | null=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'report_delivery_message_root'", "constraints": "[models.UniqueConstraint(fields=['schedule', 'recipient', 'occurrence'], name='report_delivery_occurrence_unique'), models.UniqueConstraint(fields=['requested_by', 'occurrence'], condition=models.Q(schedule__isnull=True), name='report_oneoff_request_unique'), models.CheckConstraint(condition=models.Q(schedule__isnull=False, recipient__isnull=False, destination='') \| models.Q(schedule__isnull=True, recipient__isnull=True) & ~models.Q(destination=''), name='report_delivery_kind_valid')]", "indexes": "[models.Index(fields=['status', 'next_attempt_at'], name='report_delivery_due_idx'), models.Index(fields=['provider_id'], name='report_delivery_provider_idx')]", "ordering": "['-created_at']"}`

## report_delivery/models.py::WebhookReceipt

[[F:report_delivery/models.py#126-136#4d25bf3e]]

Field | Type | Relation | Options
--- | --- | --- | ---
event_id | models.CharField |  | max_length=100; primary_key=True
provider_id | models.CharField |  | max_length=100
event_type | models.CharField |  | max_length=40
occurred_at | models.DateTimeField |  | 
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'report_delivery_webhook_event'", "indexes": "[models.Index(fields=['provider_id', 'occurred_at'], name='report_webhook_provider_idx')]"}`

## requisitions/models.py::OrderSequenceState

[[F:requisitions/models.py#5-50#3a517f85]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.BigAutoField |  | primary_key=True
partner | models.CharField |  | max_length=20; choices=[('HB', 'HB'), ('ECOCONSERVE', 'Eco-conserve')]
group_configuration | models.ForeignKey | 'core.GroupSheetConfiguration' | on_delete=models.PROTECT; related_name='requisition_order_sequences'
next_number | models.PositiveBigIntegerField |  | 
revision | models.PositiveBigIntegerField |  | 
updated_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
adjustment_reason | models.TextField |  | blank=True
created_at | models.DateTimeField |  | 
updated_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'requisition_order_sequence_state'", "constraints": "[models.UniqueConstraint(fields=['group_configuration', 'partner'], name='unique_requisition_sequence_partner')]"}`

## requisitions/models.py::OrderSequenceEvent

[[F:requisitions/models.py#53-71#3a517f85]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.BigAutoField |  | primary_key=True
sequence | models.ForeignKey | OrderSequenceState | on_delete=models.PROTECT; related_name='events'
action | models.CharField |  | max_length=24
number_before | models.PositiveBigIntegerField |  | 
number_after | models.PositiveBigIntegerField |  | 
revision_after | models.PositiveBigIntegerField |  | 
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; blank=True; on_delete=models.SET_NULL; related_name='+'
reason | models.TextField |  | 
request_id | models.CharField |  | max_length=128; blank=True; db_index=True
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'requisition_order_sequence_event'", "ordering": "['created_at', 'pk']", "constraints": "[models.UniqueConstraint(fields=['request_id'], condition=~models.Q(request_id=''), name='unique_requisition_sequence_event_request')]"}`

## requisitions/models.py::OrderNumberClaim

[[F:requisitions/models.py#74-89#3a517f85]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.BigAutoField |  | primary_key=True
sequence | models.ForeignKey | OrderSequenceState | on_delete=models.PROTECT; related_name='number_claims'
number | models.PositiveBigIntegerField |  | 
batch | models.OneToOneField | 'core.RequisitionBatch' | null=True; blank=True; on_delete=models.PROTECT; related_name='number_claim'
retired | models.BooleanField |  | 

Model metadata: `{"db_table": "'requisition_order_number_claim'", "constraints": "[models.UniqueConstraint(fields=['sequence', 'number'], name='unique_order_number_claim')]"}`

## requisitions/models.py::OrderWorkbookVersion

[[F:requisitions/models.py#92-113#3a517f85]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.BigAutoField |  | primary_key=True
batch | models.ForeignKey | 'core.RequisitionBatch' | on_delete=models.PROTECT; related_name='workbook_versions'
version | models.PositiveIntegerField |  | 
filename | models.CharField |  | max_length=255
file_content | models.BinaryField |  | 
checksum | models.CharField |  | max_length=64
farmer_ids | models.JSONField |  | 
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; on_delete=models.SET_NULL; related_name='+'
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'requisition_order_workbook_version'", "constraints": "[models.UniqueConstraint(fields=['batch', 'version'], name='unique_order_workbook_version')]"}`

## requisitions/models.py::OrderWorkspaceEvent

[[F:requisitions/models.py#116-136#3a517f85]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.BigAutoField |  | primary_key=True
batch | models.ForeignKey | 'core.RequisitionBatch' | on_delete=models.PROTECT; related_name='workspace_events'
action | models.CharField |  | max_length=24
version | models.PositiveIntegerField |  | 
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; on_delete=models.SET_NULL; related_name='+'
request_id | models.CharField |  | max_length=128
metadata | models.JSONField |  | 
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'requisition_order_workspace_event'", "constraints": "[models.UniqueConstraint(fields=['request_id'], condition=~models.Q(request_id=''), name='unique_order_workspace_request')]"}`

## tat_recognition/models.py::TatRecognitionPeriodSnapshot

[[F:tat_recognition/models.py#5-27#2ac5a4f4]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.BigAutoField |  | primary_key=True
group_id | models.CharField |  | max_length=100
scope_key | models.CharField |  | max_length=64
period_kind | models.CharField |  | max_length=8
period_key | models.CharField |  | max_length=12
facts | models.JSONField |  | 
captured_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'tat_recognition_period_snapshot'", "constraints": "[models.UniqueConstraint(fields=['group_id', 'scope_key', 'period_kind', 'period_key'], name='unique_tat_recognition_period_snapshot')]"}`

## tat_recognition/models.py::TatRecognitionLiveStanding

[[F:tat_recognition/models.py#30-47#2ac5a4f4]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.BigAutoField |  | primary_key=True
viewer | models.ForeignKey | settings.AUTH_USER_MODEL | on_delete=models.CASCADE; related_name='tat_recognition_live_standings'
group_id | models.CharField |  | max_length=100
scope_key | models.CharField |  | max_length=64
context_key | models.CharField |  | max_length=64; unique=True
ranks | models.JSONField |  | 
signature | models.CharField |  | max_length=64; blank=True
movement | models.JSONField |  | 
observed_at | models.DateTimeField |  | 
expires_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'tat_recognition_live_standing'", "indexes": "[models.Index(fields=['expires_at'], name='tat_live_expiry_idx')]"}`

## ui_review/models.py::ImmutableRecord

[[F:ui_review/models.py#9-19#0bdb0ece]]

Field | Type | Relation | Options
--- | --- | --- | ---

Model metadata: `{"abstract": "True"}`

## ui_review/models.py::ReviewRevision

[[F:ui_review/models.py#22-33#0bdb0ece]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
pattern | models.SlugField |  | max_length=80
fingerprint | models.CharField |  | max_length=64; unique=True
manifest | models.JSONField |  | 
created_by | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; on_delete=models.SET_NULL; related_name='+'
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'ui_review_revision_root'", "ordering": "['-created_at', '-id']"}`

## ui_review/models.py::ReviewDecision

[[F:ui_review/models.py#36-50#0bdb0ece]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
revision | models.ForeignKey | ReviewRevision | on_delete=models.PROTECT; related_name='decisions'
decision | models.CharField |  | max_length=16; choices=CHOICES
payload | models.JSONField |  | 
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; on_delete=models.SET_NULL; related_name='+'
request_key | models.UUIDField |  | unique=True
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'ui_review_decision_event'", "ordering": "['-created_at', '-id']"}`

## ui_review/models.py::StandardRelease

[[F:ui_review/models.py#53-65#0bdb0ece]]

Field | Type | Relation | Options
--- | --- | --- | ---
id | models.UUIDField |  | primary_key=True
version | models.PositiveIntegerField |  | unique=True
manifest | models.JSONField |  | 
fingerprint | models.CharField |  | max_length=64; unique=True
actor | models.ForeignKey | settings.AUTH_USER_MODEL | null=True; on_delete=models.SET_NULL; related_name='+'
request_key | models.UUIDField |  | unique=True
created_at | models.DateTimeField |  | 

Model metadata: `{"db_table": "'ui_review_standard_root'", "ordering": "['-version']"}`

