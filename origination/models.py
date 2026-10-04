"""Authoritative Loan Origination models; legacy tables retained during domain transfer."""
import re
import uuid
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models.functions import Lower
from django.utils import timezone


class OriginationDataField(models.Model):
    """Global semantic field used by product forms and legal PDF mappings."""

    TYPE_TEXT = 'text'
    TYPE_TEXTAREA = 'textarea'
    TYPE_NUMBER = 'number'
    TYPE_MONEY = 'money'
    TYPE_DATE = 'date'
    TYPE_PHONE = 'phone'
    TYPE_NATIONAL_ID = 'national_id'
    TYPE_CHOICE = 'choice'
    TYPE_BOOLEAN = 'boolean'
    TYPE_BRANCH = 'branch'
    TYPE_COUNTY = 'county'
    TYPE_SUB_COUNTY = 'sub_county'
    TYPE_REPEATING_GROUP = 'repeating_group'
    TYPE_CHOICES = [
        (TYPE_TEXT, 'Short text'), (TYPE_TEXTAREA, 'Long text'),
        (TYPE_NUMBER, 'Number'), (TYPE_MONEY, 'Money'), (TYPE_DATE, 'Date'),
        (TYPE_PHONE, 'Phone'), (TYPE_NATIONAL_ID, 'National ID'),
        (TYPE_CHOICE, 'Choice'), (TYPE_BOOLEAN, 'Yes / No'),
        (TYPE_BRANCH, 'Governed branch'), (TYPE_COUNTY, 'Governed county'),
        (TYPE_SUB_COUNTY, 'Governed sub-county'),
        (TYPE_REPEATING_GROUP, 'Repeatable group'),
    ]

    SOURCE_USER_INPUT = 'user_input'
    SOURCE_SYSTEM = 'system'
    SOURCE_CHOICES = [
        (SOURCE_USER_INPUT, 'User input'),
        (SOURCE_SYSTEM, 'System derived'),
    ]

    SENSITIVITY_PUBLIC = 'public'
    SENSITIVITY_INTERNAL = 'internal'
    SENSITIVITY_PII = 'pii'
    SENSITIVITY_FINANCIAL = 'financial'
    SENSITIVITY_RESTRICTED = 'restricted'
    SENSITIVITY_CHOICES = [
        (SENSITIVITY_PUBLIC, 'Public'), (SENSITIVITY_INTERNAL, 'Internal'),
        (SENSITIVITY_PII, 'Personal data (PII)'),
        (SENSITIVITY_FINANCIAL, 'Financial'),
        (SENSITIVITY_RESTRICTED, 'Restricted'),
    ]

    MASK_NONE = 'none'
    MASK_PARTIAL = 'partial'
    MASK_FULL = 'full'
    MASK_CHOICES = [
        (MASK_NONE, 'No masking'), (MASK_PARTIAL, 'Partial masking'),
        (MASK_FULL, 'Full masking'),
    ]

    REPORT_UNAVAILABLE = 'unavailable'
    REPORT_FILTER = 'filter'
    REPORT_DIMENSION = 'dimension'
    REPORT_METRIC = 'metric'
    REPORT_CHOICES = [
        (REPORT_UNAVAILABLE, 'Not reportable'), (REPORT_FILTER, 'Filter only'),
        (REPORT_DIMENSION, 'Dimension'), (REPORT_METRIC, 'Metric'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    key = models.SlugField(max_length=120, unique=True, db_comment='Key (SlugField).')
    label = models.CharField(max_length=160, db_comment='Label (CharField).')
    aliases = models.JSONField(default=list, blank=True, db_comment='Aliases (JSONField).')
    category = models.CharField(max_length=80, blank=True, default='Application', db_comment='Category (CharField).')
    data_type = models.CharField(max_length=20, choices=TYPE_CHOICES, db_comment='Data type (CharField).')
    source_type = models.CharField(
        max_length=20, choices=SOURCE_CHOICES, default=SOURCE_USER_INPUT,
    db_comment='Source type (CharField).')
    sensitivity = models.CharField(
        max_length=20, choices=SENSITIVITY_CHOICES, default=SENSITIVITY_PII,
    db_comment='Sensitivity (CharField).')
    masking_policy = models.CharField(
        max_length=16, choices=MASK_CHOICES, default=MASK_PARTIAL,
    db_comment='Masking policy (CharField).')
    reporting_use = models.CharField(
        max_length=16, choices=REPORT_CHOICES, default=REPORT_UNAVAILABLE,
    db_comment='Reporting use (CharField).')
    export_allowed = models.BooleanField(default=False, db_comment='Export allowed (BooleanField).')
    help_text = models.CharField(max_length=500, blank=True, default='', db_comment='Help text (CharField).')
    choice_options = models.JSONField(default=list, blank=True, db_comment='Choice options (JSONField).')
    structure_schema = models.JSONField(
        default=dict, blank=True,
        help_text='Immutable child-column contract for repeatable-group fields.',
    db_comment='Immutable child-column contract for repeatable-group fields.')
    active = models.BooleanField(default=True, db_index=True, db_comment='Active (BooleanField).')
    preferred_field = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.PROTECT,
        related_name='legacy_equivalent_fields',
        help_text=(
            'Preferred canonical field for this historical duplicate. Existing '
            'applications and PDF mappings continue using this field.'
        ),
    db_comment='Preferred canonical field for this historical duplicate. Existing applications and PDF mappings continue using this field.')
    terminology_reviewed_distinct = models.BooleanField(
        default=False,
        help_text='Confirm that this similarly named field has a genuinely distinct meaning.',
    db_comment='Confirm that this similarly named field has a genuinely distinct meaning.')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='created_origination_data_fields',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Created at (DateTimeField).')
    updated_at = models.DateTimeField(auto_now=True, db_comment='Updated at (DateTimeField).')

    class Meta:
        db_table = 'core_originationdatafield'
        db_table_comment = 'Domain: origination. Purpose: Global semantic field used by product forms and legal PDF mappings. Classification: authoritative_record. Source of truth: yes. Lifecycle: active. Retention: Retained with the owning business record according to its workflow policy. Parents: auth.User, origination.OriginationDataField. Children: origination.OriginationDataField, origination.OriginationDataFieldEvent, origination.OriginationFieldReviewIssue, origination.OriginationReportingValue. Code usage: owning Django model and workflow service.'
        ordering = ['category', 'label', 'key']
        indexes = [models.Index(fields=['active', 'category', 'label'])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(preferred_field__isnull=True) | models.Q(active=False),
                name='orig_field_preferred_requires_inactive',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(preferred_field__isnull=True)
                    | models.Q(terminology_reviewed_distinct=False)
                ),
                name='orig_field_preferred_not_distinct',
            ),
        ]

    def __str__(self):
        return f'{self.label} ({self.key})'

    def clean(self):
        super().clean()
        if self.preferred_field_id:
            if self.preferred_field_id == self.pk:
                raise ValidationError({'preferred_field': 'A field cannot replace itself.'})
            if self.preferred_field.data_type != self.data_type:
                raise ValidationError({'preferred_field': 'The preferred field must use the same data type.'})
            if not self.preferred_field.active:
                raise ValidationError({'preferred_field': 'Choose an active preferred field.'})
            if self.active:
                raise ValidationError({'active': 'A historical duplicate with a preferred field must be inactive.'})
            if self.terminology_reviewed_distinct:
                raise ValidationError({
                    'terminology_reviewed_distinct': (
                        'A field cannot be both a historical duplicate and confirmed distinct.'
                    ),
                })
        aliases = self.aliases or []
        if not isinstance(aliases, list) or any(not isinstance(item, str) for item in aliases):
            raise ValidationError({'aliases': 'Aliases must be a list of text values.'})
        normalized_aliases = [item.strip() for item in aliases if item.strip()]
        if len({item.casefold() for item in normalized_aliases}) != len(normalized_aliases):
            raise ValidationError({'aliases': 'Aliases cannot contain duplicates.'})
        self.aliases = normalized_aliases
        options = self.choice_options or []
        if self.data_type == self.TYPE_CHOICE:
            if not isinstance(options, list) or not options:
                raise ValidationError({'choice_options': 'Choice fields require canonical options.'})
            codes = []
            for option in options:
                if not isinstance(option, dict):
                    raise ValidationError({'choice_options': 'Each choice requires a code and label.'})
                code = str(option.get('code') or '').strip()
                label = str(option.get('label') or '').strip()
                if not code or not label:
                    raise ValidationError({'choice_options': 'Each choice requires a code and label.'})
                codes.append(code)
            if len(codes) != len(set(codes)):
                raise ValidationError({'choice_options': 'Canonical choice codes must be unique.'})
        elif options:
            raise ValidationError({'choice_options': 'Only choice fields may define choice options.'})
        structure = self.structure_schema or {}
        if self.data_type == self.TYPE_REPEATING_GROUP:
            if not isinstance(structure, dict):
                raise ValidationError({'structure_schema': 'Repeatable-group structure must be an object.'})
            columns = structure.get('columns')
            if not isinstance(columns, list) or not columns:
                raise ValidationError({'structure_schema': 'Repeatable groups require child columns.'})
            keys = []
            allowed_types = {
                self.TYPE_TEXT, self.TYPE_TEXTAREA, self.TYPE_NUMBER, self.TYPE_MONEY,
                self.TYPE_DATE, self.TYPE_PHONE, self.TYPE_NATIONAL_ID,
                self.TYPE_CHOICE, self.TYPE_BOOLEAN,
            }
            for column in columns:
                if not isinstance(column, dict):
                    raise ValidationError({'structure_schema': 'Every repeatable-group column must be an object.'})
                key = str(column.get('key') or '').strip()
                column_type = str(column.get('type') or '').strip()
                if not re.fullmatch(r'[a-z0-9_]+', key) or column_type not in allowed_types:
                    raise ValidationError({'structure_schema': 'Each child column requires a stable key and supported scalar type.'})
                keys.append(key)
            if len(keys) != len(set(keys)):
                raise ValidationError({'structure_schema': 'Repeatable-group child keys must be unique.'})
            minimum = int(structure.get('min_items', 0) or 0)
            maximum = int(structure.get('max_items', 0) or 0)
            if minimum < 0 or maximum < 1 or minimum > maximum or maximum > 50:
                raise ValidationError({'structure_schema': 'Repeatable-group item limits are invalid.'})
        elif structure:
            raise ValidationError({'structure_schema': 'Only repeatable-group fields may define a structure.'})
        for option in options:
            code = str(option.get('code') or '')
            if not re.fullmatch(r'[a-z0-9_]+', code):
                raise ValidationError({
                    'choice_options': 'Canonical choice codes may contain only lowercase letters, numbers, and underscores.',
                })
        if self.reporting_use == self.REPORT_METRIC and self.data_type not in {
            self.TYPE_NUMBER, self.TYPE_MONEY,
        }:
            raise ValidationError({'reporting_use': 'Only numeric or money fields may be report metrics.'})

    def save(self, *args, **kwargs):
        if self.pk:
            original = type(self).objects.filter(pk=self.pk).values(
                'key', 'data_type', 'choice_options', 'structure_schema',
            ).first()
            if original and (original['key'] != self.key or original['data_type'] != self.data_type):
                raise ValidationError('Canonical field keys and data types are immutable.')
            if original and original['structure_schema'] != (self.structure_schema or {}):
                raise ValidationError('Canonical repeatable-group structures are immutable.')
            if original and self.data_type == self.TYPE_CHOICE:
                previous_codes = {
                    str(item.get('code') or '') for item in (original['choice_options'] or [])
                    if isinstance(item, dict)
                }
                current_codes = {
                    str(item.get('code') or '') for item in (self.choice_options or [])
                    if isinstance(item, dict)
                }
                if previous_codes - current_codes:
                    raise ValidationError(
                        'Canonical choice codes cannot be removed; mark obsolete options inactive.',
                    )
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Canonical origination fields cannot be deleted; deactivate them instead.')



class OriginationDataFieldEvent(models.Model):
    """Append-only, value-free audit trail for catalogue governance."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    data_field = models.ForeignKey(
        OriginationDataField, on_delete=models.PROTECT, related_name='events',
    db_comment='Reference to core_originationdatafield; deletion behavior: PROTECT.')
    action = models.CharField(max_length=40, db_index=True, db_comment='Action (CharField).')
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='origination_data_field_events',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    metadata = models.JSONField(default=dict, blank=True, db_comment='Metadata (JSONField).')
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True, db_comment='Occurred at (DateTimeField).')

    class Meta:
        db_table = 'core_originationdatafieldevent'
        db_table_comment = 'Domain: origination. Purpose: Append-only, value-free audit trail for catalogue governance. Classification: immutable_event. Source of truth: yes. Lifecycle: active. Retention: Retained with the permanent workflow or compliance audit record. Parents: auth.User, origination.OriginationDataField. Children: none. Code usage: owning Django model and workflow service.'
        ordering = ['occurred_at', 'id']

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Origination data-field events are append-only.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Origination data-field events cannot be deleted.')



class OriginationProductDefinition(models.Model):
    """Versioned, inactive-by-default contract for one loan-origination form."""

    STATUS_DRAFT = 'draft'
    STATUS_PUBLISHED = 'published'
    STATUS_RETIRED = 'retired'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_PUBLISHED, 'Published'),
        (STATUS_RETIRED, 'Retired'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    product_version = models.ForeignKey(
        'core.ProductVersion', null=True, blank=True, on_delete=models.PROTECT,
        related_name='origination_definitions',
    db_comment='Reference to core_productversion; deletion behavior: PROTECT.')
    product_key = models.SlugField(max_length=80, db_index=True, db_comment='Product key (SlugField).')
    name = models.CharField(max_length=160, db_comment='Name (CharField).')
    version = models.PositiveIntegerField(default=1, db_comment='Version (PositiveIntegerField).')
    form_schema = models.JSONField(default=dict, db_comment='Form schema (JSONField).')
    signer_rules = models.JSONField(default=list, db_comment='Signer rules (JSONField).')
    document_type = models.CharField(max_length=80, db_comment='Document type (CharField).')
    document_template_name = models.CharField(max_length=180, blank=True, default='', db_comment='Document template name (CharField).')
    document_template_version = models.PositiveIntegerField(default=1, db_comment='Document template version (PositiveIntegerField).')
    document_template_sha256 = models.CharField(max_length=64, blank=True, default='', db_comment='Document template sha256 (CharField).')
    is_active = models.BooleanField(default=False, db_index=True, db_comment='Is active (BooleanField).')
    lifecycle_status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True,
    db_comment='Lifecycle status (CharField).')
    supersedes = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.PROTECT,
        related_name='superseded_by_versions',
    db_comment='Reference to core_originationproductdefinition; deletion behavior: PROTECT.')
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='published_origination_product_definitions',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    published_at = models.DateTimeField(null=True, blank=True, db_comment='Published at (DateTimeField).')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='created_origination_product_definitions',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Created at (DateTimeField).')
    updated_at = models.DateTimeField(auto_now=True, db_comment='Updated at (DateTimeField).')

    class Meta:
        db_table = 'core_originationproductdefinition'
        db_table_comment = 'Domain: origination. Purpose: Versioned, inactive-by-default contract for one loan-origination form. Classification: configuration. Source of truth: yes. Lifecycle: active. Retention: Retain while referenced; retire or deactivate instead of deleting governed history. Parents: auth.User, origination.OriginationProductDefinition, core.ProductVersion. Children: origination.LoanOriginationApplication, origination.OriginationDocumentTemplate, origination.OriginationFieldReviewIssue, origination.OriginationProductDefinition, origination.OriginationProductDefinitionEvent, origination.OriginationProductDocumentAssignment. Code usage: owning Django model and workflow service.'
        ordering = ['product_key', '-version']
        constraints = [
            models.UniqueConstraint(
                fields=['product_key', 'version'], name='unique_origination_product_version',
            ),
            models.UniqueConstraint(
                fields=['product_key'], condition=models.Q(is_active=True),
                name='one_active_origination_product_version',
            ),
        ]
        indexes = [models.Index(
            fields=['product_key', 'is_active'], name='core_origin_product_67c040_idx',
        )]

    def __str__(self):
        return f'{self.name} v{self.version}'

    def clean(self):
        super().clean()
        if self.product_version_id:
            if self.product_key != self.product_version.product.code:
                raise ValidationError({'product_key': 'Origination product key must match the global product code.'})
            if self.name != self.product_version.product.name:
                raise ValidationError({'name': 'Origination product name must match the global product name.'})
        if self.is_active or self.lifecycle_status == self.STATUS_PUBLISHED:
            from origination.services.loan_origination import OriginationError, validate_product_definition
            try:
                validate_product_definition(self)
            except OriginationError as exc:
                raise ValidationError(str(exc)) from exc



class OriginationProductDefinitionEvent(models.Model):
    """Append-only lifecycle history for a versioned origination product."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    product_definition = models.ForeignKey(
        OriginationProductDefinition, on_delete=models.PROTECT, related_name='events',
    db_comment='Reference to core_originationproductdefinition; deletion behavior: PROTECT.')
    action = models.CharField(max_length=40, db_index=True, db_comment='Action (CharField).')
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='origination_product_definition_events',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    metadata = models.JSONField(default=dict, blank=True, db_comment='Metadata (JSONField).')
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True, db_comment='Occurred at (DateTimeField).')

    class Meta:
        db_table = 'core_originationproductdefinitionevent'
        db_table_comment = 'Domain: origination. Purpose: Append-only lifecycle history for a versioned origination product. Classification: immutable_event. Source of truth: yes. Lifecycle: active. Retention: Retained with the permanent workflow or compliance audit record. Parents: auth.User, origination.OriginationProductDefinition. Children: none. Code usage: owning Django model and workflow service.'
        ordering = ['occurred_at', 'id']

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Origination product events are append-only.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Origination product events cannot be deleted.')



class OriginationFieldReviewIssue(models.Model):
    """Tracked exit path for a legacy schema field without a safe catalogue binding."""

    STATUS_OPEN = 'open'
    STATUS_RESOLVED = 'resolved'
    STATUS_ACCEPTED = 'accepted_legacy'
    STATUS_CHOICES = [
        (STATUS_OPEN, 'Needs review'), (STATUS_RESOLVED, 'Resolved'),
        (STATUS_ACCEPTED, 'Accepted as legacy'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    product_definition = models.ForeignKey(
        OriginationProductDefinition, on_delete=models.PROTECT,
        related_name='field_review_issues',
    db_comment='Reference to core_originationproductdefinition; deletion behavior: PROTECT.')
    legacy_key = models.CharField(max_length=120, db_comment='Legacy key (CharField).')
    legacy_type = models.CharField(max_length=20, blank=True, default='text', db_comment='Legacy type (CharField).')
    legacy_label = models.CharField(max_length=160, blank=True, default='', db_comment='Legacy label (CharField).')
    reason = models.CharField(max_length=80, blank=True, default='missing_catalogue_field', db_comment='Reason (CharField).')
    suggested_field = models.ForeignKey(
        OriginationDataField, null=True, blank=True, on_delete=models.PROTECT,
        related_name='suggested_legacy_reviews',
    db_comment='Reference to core_originationdatafield; deletion behavior: PROTECT.')
    resolution_field = models.ForeignKey(
        OriginationDataField, null=True, blank=True, on_delete=models.PROTECT,
        related_name='resolved_legacy_reviews',
    db_comment='Reference to core_originationdatafield; deletion behavior: PROTECT.')
    status = models.CharField(
        max_length=24, choices=STATUS_CHOICES, default=STATUS_OPEN, db_index=True,
    db_comment='Status (CharField).')
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='assigned_origination_field_reviews',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    resolution_notes = models.TextField(blank=True, default='', db_comment='Resolution notes (TextField).')
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='resolved_origination_field_reviews',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    resolved_at = models.DateTimeField(null=True, blank=True, db_comment='Resolved at (DateTimeField).')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Created at (DateTimeField).')
    updated_at = models.DateTimeField(auto_now=True, db_comment='Updated at (DateTimeField).')

    class Meta:
        db_table = 'core_originationfieldreviewissue'
        db_table_comment = 'Domain: origination. Purpose: Tracked exit path for a legacy schema field without a safe catalogue binding. Classification: authoritative_record. Source of truth: yes. Lifecycle: active. Retention: Retained with the owning business record according to its workflow policy. Parents: auth.User, origination.OriginationDataField, origination.OriginationProductDefinition. Children: none. Code usage: owning Django model and workflow service.'
        ordering = ['status', '-created_at']
        constraints = [models.UniqueConstraint(
            fields=['product_definition', 'legacy_key'],
            name='unique_origination_field_review_key',
        )]
        indexes = [models.Index(fields=['status', 'updated_at'])]

    def __str__(self):
        return f'{self.product_definition}: {self.legacy_key}'

    def clean(self):
        super().clean()
        if self.status == self.STATUS_RESOLVED and not self.resolution_field_id:
            raise ValidationError({'resolution_field': 'Choose the canonical resolution field.'})
        if self.status == self.STATUS_ACCEPTED and not self.resolution_notes.strip():
            raise ValidationError({'resolution_notes': 'Explain why this field remains legacy.'})
        if self.resolution_field_id and self.resolution_field.data_type != self.legacy_type:
            raise ValidationError({'resolution_field': 'The canonical field must use the same data type.'})



class OriginationDocumentTemplate(models.Model):
    """Immutable Drive-backed PDF/config pair approved for origination rendering."""

    STATUS_READY = 'ready'
    STATUS_ACTIVE = 'active'
    STATUS_RETIRED = 'retired'
    STATUS_UPLOAD_FAILED = 'upload_failed'
    STATUS_CHOICES = [
        (STATUS_READY, 'Ready for review'),
        (STATUS_ACTIVE, 'Active'),
        (STATUS_RETIRED, 'Retired'),
        (STATUS_UPLOAD_FAILED, 'Upload failed'),
    ]

    ROLE_PRIMARY = 'primary'
    ROLE_SUPPORTING = 'supporting'
    ROLE_CHOICES = [
        (ROLE_PRIMARY, 'Primary LAF'),
        (ROLE_SUPPORTING, 'Supporting document'),
    ]
    INCLUDE_REQUIRED = 'required'
    INCLUDE_CONDITIONAL = 'conditional_required'
    INCLUDE_OPTIONAL = 'optional'
    INCLUDE_CHOICES = [
        (INCLUDE_REQUIRED, 'Always required'),
        (INCLUDE_CONDITIONAL, 'Required when rule matches'),
        (INCLUDE_OPTIONAL, 'Officer selectable'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    product_definition = models.ForeignKey(
        OriginationProductDefinition, null=True, blank=True, on_delete=models.PROTECT,
        related_name='document_templates',
    db_comment='Reference to core_originationproductdefinition; deletion behavior: PROTECT.')
    eligible_products = models.ManyToManyField(
        'core.Product', through='OriginationDocumentProductEligibility',
        related_name='eligible_origination_document_templates', blank=True,
        help_text=(
            'Global products allowed to use this exact immutable document version. '
            'An empty list makes the document unavailable for new applications.'
        ),
    )
    document_key = models.SlugField(max_length=80, default='primary', db_index=True, db_comment='Document key (SlugField).')
    document_role = models.CharField(
        max_length=16, choices=ROLE_CHOICES, default=ROLE_PRIMARY, db_index=True,
    db_comment='Document role (CharField).')
    inclusion_mode = models.CharField(
        max_length=24, choices=INCLUDE_CHOICES, default=INCLUDE_REQUIRED,
    db_comment='Inclusion mode (CharField).')
    display_order = models.PositiveSmallIntegerField(default=0, db_comment='Display order (PositiveSmallIntegerField).')
    officer_selectable = models.BooleanField(default=False, db_comment='Officer selectable (BooleanField).')
    default_selected = models.BooleanField(default=False, db_comment='Default selected (BooleanField).')
    applicability_rule = models.JSONField(default=dict, blank=True, db_comment='Applicability rule (JSONField).')
    form_schema = models.JSONField(default=dict, blank=True, db_comment='Form schema (JSONField).')
    signer_rules = models.JSONField(default=list, blank=True, db_comment='Signer rules (JSONField).')
    document_type = models.SlugField(max_length=80, db_index=True, db_comment='Document type (SlugField).')
    name = models.CharField(max_length=180, db_comment='Name (CharField).')
    version = models.PositiveIntegerField(db_comment='Version (PositiveIntegerField).')
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_READY, db_index=True, db_comment='Status (CharField).')
    source_filename = models.CharField(max_length=255, db_comment='Source filename (CharField).')
    source_sha256 = models.CharField(max_length=64, db_index=True, db_comment='Source sha256 (CharField).')
    source_byte_size = models.PositiveBigIntegerField(db_comment='Source byte size (PositiveBigIntegerField).')
    page_count = models.PositiveIntegerField(db_comment='Page count (PositiveIntegerField).')
    placement_config = models.JSONField(default=dict, db_comment='Placement config (JSONField).')
    published_configuration_revision = models.ForeignKey(
        'OriginationTemplateConfigurationRevision', null=True, blank=True,
        on_delete=models.PROTECT, related_name='+',
    db_comment='Reference to core_originationtemplateconfigurationrevision; deletion behavior: PROTECT.')
    native_consent_policy = models.ForeignKey(
        'OriginationConsentPolicyVersion', null=True, blank=True,
        on_delete=models.PROTECT, related_name='native_document_templates',
        help_text='Approved consent wording embedded directly in this immutable source PDF.',
    db_comment='Approved consent wording embedded directly in this immutable source PDF.')
    native_consent_attestation_reference = models.CharField(max_length=160, blank=True, default='', db_comment='Native consent attestation reference (CharField).')
    native_consent_attested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='attested_native_origination_consent_templates',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    native_consent_attested_at = models.DateTimeField(null=True, blank=True, db_comment='Native consent attested at (DateTimeField).')
    drive_file_id = models.CharField(max_length=255, blank=True, default='', db_comment='Drive file id (CharField).')
    drive_url = models.URLField(max_length=1000, blank=True, default='', db_comment='Drive url (CharField).')
    upload_error = models.TextField(blank=True, default='', db_comment='Upload error (TextField).')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='created_origination_document_templates',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='activated_origination_document_templates',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    activated_at = models.DateTimeField(null=True, blank=True, db_comment='Activated at (DateTimeField).')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Created at (DateTimeField).')
    updated_at = models.DateTimeField(auto_now=True, db_comment='Updated at (DateTimeField).')

    class Meta:
        db_table = 'core_originationdocumenttemplate'
        db_table_comment = 'Domain: origination. Purpose: Immutable Drive-backed PDF/config pair approved for origination rendering. Classification: configuration. Source of truth: yes. Lifecycle: active. Retention: Retain while referenced; retire or deactivate instead of deleting governed history. Parents: auth.User, origination.OriginationConsentPolicyVersion, origination.OriginationProductDefinition, origination.OriginationTemplateConfigurationRevision. Children: origination.OriginationApplicationDocument, origination.OriginationDocumentProductEligibility, origination.OriginationDocumentTemplateEvent, origination.OriginationProductDocumentAssignment, origination.OriginationTemplateConfigurationRevision. Code usage: owning Django model and workflow service.'
        ordering = ['product_definition', 'display_order', 'document_key', '-version']
        constraints = [
            models.UniqueConstraint(
                fields=['document_type', 'version'],
                condition=models.Q(status__in=['ready', 'active']),
                name='unique_ready_active_orig_document_version',
            ),
            models.UniqueConstraint(
                fields=['document_type'], condition=models.Q(status='active'),
                name='one_active_origination_document',
            ),
        ]

    def __str__(self):
        return f'{self.name} v{self.version}'

    def clean(self):
        super().clean()
        errors = {}
        if self.document_role == self.ROLE_PRIMARY:
            if self.document_key != 'primary':
                errors['document_key'] = 'The primary LAF must use the key "primary".'
            if self.inclusion_mode != self.INCLUDE_REQUIRED:
                errors['inclusion_mode'] = 'The primary LAF is always required.'
            if self.officer_selectable:
                errors['officer_selectable'] = 'The primary LAF cannot be optional.'
        elif self.document_key == 'primary':
            errors['document_key'] = 'Supporting documents require their own stable key.'
        if self.inclusion_mode == self.INCLUDE_OPTIONAL and not self.officer_selectable:
            errors['officer_selectable'] = 'Optional documents must be officer selectable.'
        if self.inclusion_mode != self.INCLUDE_OPTIONAL and self.default_selected:
            errors['default_selected'] = 'Only optional documents can be selected by default.'
        if errors:
            raise ValidationError(errors)



class OriginationDocumentProductEligibility(models.Model):
    """Explicit product allowlist for one immutable catalogue document version."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    template = models.ForeignKey(
        OriginationDocumentTemplate, on_delete=models.PROTECT,
        related_name='product_eligibilities',
    db_comment='Reference to core_originationdocumenttemplate; deletion behavior: PROTECT.')
    product = models.ForeignKey(
        'core.Product', on_delete=models.PROTECT,
        related_name='origination_document_eligibilities',
    db_comment='Reference to core_product; deletion behavior: PROTECT.')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='created_origination_document_eligibilities',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Created at (DateTimeField).')

    class Meta:
        db_table = 'core_originationdocumentproducteligibility'
        db_table_comment = 'Domain: origination. Purpose: Current product allowlist for one immutable Origination catalogue document version. Classification: business_link. Source of truth: yes. Lifecycle: active. Retention: Retained while the catalogue document or product history requires it. Parents: auth.User, origination.OriginationDocumentTemplate, core.Product. Children: none. Code usage: owning Django model and workflow service.'
        ordering = ['template__document_type', 'product__name']
        constraints = [models.UniqueConstraint(
            fields=['template', 'product'],
            name='unique_origination_document_product_eligibility',
        )]

    def __str__(self):
        return f'{self.template} â†’ {self.product}'



class OriginationProductDocumentAssignment(models.Model):
    """Immutable product-version assignment of an approved shared document family."""

    VERSION_LATEST_COMPATIBLE = 'latest_compatible'
    VERSION_PINNED = 'pinned'
    VERSION_POLICY_CHOICES = [
        (VERSION_LATEST_COMPATIBLE, 'Latest published compatible version'),
        (VERSION_PINNED, 'Pin exact template version'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    product_definition = models.ForeignKey(
        OriginationProductDefinition, on_delete=models.PROTECT,
        related_name='document_assignments',
    db_comment='Reference to core_originationproductdefinition; deletion behavior: PROTECT.')
    template = models.ForeignKey(
        OriginationDocumentTemplate, on_delete=models.PROTECT,
        related_name='product_assignments',
        help_text='Compatibility baseline and family identity for this assignment.',
    db_comment='Compatibility baseline and family identity for this assignment.')
    version_policy = models.CharField(
        max_length=24, choices=VERSION_POLICY_CHOICES,
        default=VERSION_LATEST_COMPATIBLE,
        help_text='Latest-compatible affects new applications only; every application snapshots its resolved version.',
    db_comment='Latest-compatible affects new applications only; every application snapshots its resolved version.')
    document_key = models.SlugField(max_length=80, db_comment='Document key (SlugField).')
    name = models.CharField(max_length=180, db_comment='Name (CharField).')
    display_order = models.PositiveSmallIntegerField(default=10, db_comment='Display order (PositiveSmallIntegerField).')
    inclusion_mode = models.CharField(
        max_length=24, choices=OriginationDocumentTemplate.INCLUDE_CHOICES,
        default=OriginationDocumentTemplate.INCLUDE_REQUIRED,
    db_comment='Inclusion mode (CharField).')
    officer_selectable = models.BooleanField(default=False, db_comment='Officer selectable (BooleanField).')
    default_selected = models.BooleanField(default=False, db_comment='Default selected (BooleanField).')
    applicability_rule = models.JSONField(default=dict, blank=True, db_comment='Applicability rule (JSONField).')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='created_origination_document_assignments',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Created at (DateTimeField).')

    class Meta:
        db_table = 'core_originationproductdocumentassignment'
        db_table_comment = 'Domain: origination. Purpose: Version-policy assignment between a legacy product definition and document family. Classification: business_assignment. Source of truth: yes. Lifecycle: compatibility. Retention: Retained for historical product-definition and application compatibility. Parents: auth.User, origination.OriginationDocumentTemplate, origination.OriginationProductDefinition. Children: origination.OriginationApplicationDocument. Code usage: owning Django model and workflow service.'
        ordering = ['product_definition', 'display_order', 'document_key']
        constraints = [
            models.UniqueConstraint(
                fields=['product_definition', 'document_key'],
                name='unique_origination_product_document_key',
            ),
            models.UniqueConstraint(
                fields=['product_definition', 'template'],
                name='unique_origination_product_template_assignment',
            ),
        ]

    def __str__(self):
        return f'{self.product_definition}: {self.name}'

    def clean(self):
        super().clean()
        errors = {}
        if self.template_id:
            if (
                self.template.document_role == OriginationDocumentTemplate.ROLE_PRIMARY
                and self.template.product_definition_id is not None
            ):
                errors['template'] = 'A reusable primary LAF must be a global template.'
            if (
                self.template.product_definition_id not in (None, self.product_definition_id)
                and self.template.status not in {
                    OriginationDocumentTemplate.STATUS_ACTIVE,
                    OriginationDocumentTemplate.STATUS_RETIRED,
                }
            ):
                errors['template'] = 'Only an immutable published legacy template can be shared from another product version.'
            if (
                self.version_policy == self.VERSION_LATEST_COMPATIBLE
                and self.template.product_definition_id is not None
            ):
                errors['version_policy'] = 'Latest-compatible requires a global shared-template family.'
            if self.template.document_role == OriginationDocumentTemplate.ROLE_PRIMARY:
                if self.document_key != 'primary':
                    errors['document_key'] = 'A reusable primary LAF must use the key "primary".'
                if self.inclusion_mode != OriginationDocumentTemplate.INCLUDE_REQUIRED:
                    errors['inclusion_mode'] = 'The primary LAF is always required.'
                if self.officer_selectable:
                    errors['officer_selectable'] = 'The primary LAF cannot be officer selectable.'
                if self.default_selected:
                    errors['default_selected'] = 'The primary LAF is selected automatically.'
                if self.applicability_rule:
                    errors['applicability_rule'] = 'The primary LAF cannot have an applicability rule.'
            elif self.document_key == 'primary':
                errors['document_key'] = 'Supporting documents require their own stable key.'
        if self.inclusion_mode == OriginationDocumentTemplate.INCLUDE_OPTIONAL and not self.officer_selectable:
            errors['officer_selectable'] = 'Optional documents must be officer selectable.'
        if self.inclusion_mode != OriginationDocumentTemplate.INCLUDE_OPTIONAL and self.default_selected:
            errors['default_selected'] = 'Only optional documents can be selected by default.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.product_definition.lifecycle_status != OriginationProductDefinition.STATUS_DRAFT:
            raise ValidationError('Document assignments are immutable; create the next product version.')
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.product_definition.lifecycle_status != OriginationProductDefinition.STATUS_DRAFT:
            raise ValidationError('Published document assignments cannot be deleted; replace them in the next product version.')
        return super().delete(*args, **kwargs)



class OriginationDocumentTemplateEvent(models.Model):
    """Append-only audit trail for legal template lifecycle changes."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    template = models.ForeignKey(
        OriginationDocumentTemplate, on_delete=models.PROTECT, related_name='events',
    db_comment='Reference to core_originationdocumenttemplate; deletion behavior: PROTECT.')
    action = models.CharField(max_length=40, db_index=True, db_comment='Action (CharField).')
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='origination_document_template_events',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    metadata = models.JSONField(default=dict, blank=True, db_comment='Metadata (JSONField).')
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True, db_comment='Occurred at (DateTimeField).')

    class Meta:
        db_table = 'core_originationdocumenttemplateevent'
        db_table_comment = 'Domain: origination. Purpose: Append-only audit trail for legal template lifecycle changes. Classification: immutable_event. Source of truth: yes. Lifecycle: active. Retention: Retained with the permanent workflow or compliance audit record. Parents: auth.User, origination.OriginationDocumentTemplate. Children: none. Code usage: owning Django model and workflow service.'
        ordering = ['occurred_at', 'id']

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Origination document template events are append-only.')
        return super().save(*args, **kwargs)



class OriginationTemplateConfigurationRevision(models.Model):
    """Append-only saved calibration revision for one immutable source PDF."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    template = models.ForeignKey(
        OriginationDocumentTemplate, on_delete=models.PROTECT, related_name='configuration_revisions',
    db_comment='Reference to core_originationdocumenttemplate; deletion behavior: PROTECT.')
    revision = models.PositiveIntegerField(db_comment='Revision (PositiveIntegerField).')
    configuration = models.JSONField(default=dict, db_comment='Configuration (JSONField).')
    is_published = models.BooleanField(default=False, db_index=True, db_comment='Is published (BooleanField).')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='origination_template_configuration_revisions',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Created at (DateTimeField).')
    published_at = models.DateTimeField(null=True, blank=True, db_comment='Published at (DateTimeField).')

    class Meta:
        db_table = 'core_originationtemplateconfigurationrevision'
        db_table_comment = 'Domain: origination. Purpose: Append-only saved calibration revision for one immutable source PDF. Classification: authoritative_record. Source of truth: yes. Lifecycle: active. Retention: Retained with the owning business record according to its workflow policy. Parents: auth.User, origination.OriginationDocumentTemplate. Children: origination.OriginationDocumentTemplate. Code usage: owning Django model and workflow service.'
        ordering = ['template', '-revision']
        constraints = [
            models.UniqueConstraint(
                fields=['template', 'revision'], name='unique_origination_template_config_revision',
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Origination template configuration revisions are append-only.')
        return super().save(*args, **kwargs)



class LoanOriginationApplication(models.Model):
    """Canonical, revision-controlled application captured by a field officer."""

    STATUS_DRAFT = 'draft'
    STATUS_READY_FOR_REVIEW = 'ready_for_review'
    STATUS_REVIEWED = 'reviewed'
    STATUS_SIGNING_PENDING = 'signing_pending'
    STATUS_PARTIALLY_SIGNED = 'partially_signed'
    STATUS_FULLY_SIGNED = 'fully_signed'
    STATUS_SIGNED_PENDING_APPROVAL = 'signed_pending_approval'
    STATUS_APPROVED = 'approved'
    STATUS_CORRECTION_REQUIRED = 'correction_required'
    STATUS_DECLINED = 'declined'
    STATUS_EXPIRED = 'expired'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_READY_FOR_REVIEW, 'Ready for review'),
        (STATUS_REVIEWED, 'Reviewed'),
        (STATUS_SIGNING_PENDING, 'Signing pending'),
        (STATUS_PARTIALLY_SIGNED, 'Partially signed'),
        (STATUS_FULLY_SIGNED, 'Fully signed'),
        (STATUS_SIGNED_PENDING_APPROVAL, 'Signed â€” pending JBL approval'),
        (STATUS_APPROVED, 'Approved and locked'),
        (STATUS_CORRECTION_REQUIRED, 'Correction required'),
        (STATUS_DECLINED, 'Declined'),
        (STATUS_EXPIRED, 'Expired'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    reference_number = models.CharField(max_length=80, unique=True, db_index=True, db_comment='Reference number (CharField).')
    product_definition = models.ForeignKey(
        OriginationProductDefinition, on_delete=models.PROTECT, related_name='applications',
    db_comment='Reference to core_originationproductdefinition; deletion behavior: PROTECT.')
    product_version = models.ForeignKey(
        'core.ProductVersion', null=True, blank=True, on_delete=models.PROTECT,
        related_name='origination_applications',
    db_comment='Reference to core_productversion; deletion behavior: PROTECT.')
    customer = models.ForeignKey(
        'core.JawabuCustomer', null=True, blank=True, on_delete=models.PROTECT,
        related_name='origination_applications',
    db_comment='Reference to core_jawabucustomer; deletion behavior: PROTECT.')
    officer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='loan_origination_applications',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    group_configuration = models.ForeignKey(
        'core.GroupSheetConfiguration', null=True, blank=True, on_delete=models.PROTECT,
        related_name='origination_applications',
        db_comment='Origination creation scope; historical applications remain ungrouped.',
    )
    branch = models.CharField(max_length=128, blank=True, default='', db_index=True, db_comment='Branch (CharField).')
    branch_ref = models.ForeignKey(
        'core.OperationalLocation', null=True, blank=True, on_delete=models.PROTECT,
        limit_choices_to={'location_type': 'branch'}, related_name='origination_applications',
    db_comment='Reference to core_operationallocation; deletion behavior: PROTECT.')
    county_ref = models.ForeignKey(
        'core.OperationalLocation', null=True, blank=True, on_delete=models.PROTECT,
        limit_choices_to={'location_type': 'county'}, related_name='origination_county_applications',
    db_comment='Reference to core_operationallocation; deletion behavior: PROTECT.')
    sub_county_ref = models.ForeignKey(
        'core.OperationalLocation', null=True, blank=True, on_delete=models.PROTECT,
        limit_choices_to={'location_type': 'sub_county'}, related_name='origination_sub_county_applications',
    db_comment='Reference to core_operationallocation; deletion behavior: PROTECT.')
    location_snapshot = models.JSONField(default=dict, blank=True, db_comment='Location snapshot (JSONField).')
    status = models.CharField(
        max_length=32, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True,
    db_comment='Status (CharField).')
    revision = models.PositiveIntegerField(default=1, db_comment='Revision (PositiveIntegerField).')
    form_payload = models.JSONField(default=dict, db_comment='Form payload (JSONField).')
    schema_snapshot = models.JSONField(default=dict, db_comment='Schema snapshot (JSONField).')
    signer_rules_snapshot = models.JSONField(default=list, db_comment='Signer rules snapshot (JSONField).')
    template_configuration_snapshot = models.JSONField(default=dict, blank=True, db_comment='Template configuration snapshot (JSONField).')
    primary_previewed_revision = models.PositiveIntegerField(null=True, blank=True, db_comment='Primary previewed revision (PositiveIntegerField).')
    product_terms_snapshot = models.JSONField(default=dict, blank=True, db_comment='Product terms snapshot (JSONField).')
    product_quote_snapshot = models.JSONField(default=dict, blank=True, db_comment='Product quote snapshot (JSONField).')
    product_requirement_evidence = models.JSONField(default=dict, blank=True, db_comment='Product requirement evidence (JSONField).')
    product_custom_values = models.JSONField(default=dict, blank=True, db_comment='Product custom values (JSONField).')
    product_selected_fee_keys = models.JSONField(default=list, blank=True, db_comment='Product selected fee keys (JSONField).')
    identity_snapshot = models.JSONField(default=dict, blank=True, db_comment='Identity snapshot (JSONField).')
    client_request_id = models.CharField(max_length=128, blank=True, default='', db_index=True, db_comment='Client request id (CharField).')
    creation_request_digest = models.CharField(max_length=64, blank=True, default='', db_index=True, db_comment='Creation request digest (CharField).')
    supersedes_application = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.PROTECT,
        related_name='replacement_applications',
        help_text='Cancelled draft replaced through the audited Main LAF restart flow.',
    db_comment='Cancelled draft replaced through the audited Main LAF restart flow.')
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='reviewed_loan_origination_applications',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    recheck_assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='assigned_origination_rechecks',
        help_text='Checker responsible for verifying the current correction cycle.',
    db_comment='Checker responsible for verifying the current correction cycle.')
    reviewed_at = models.DateTimeField(null=True, blank=True, db_comment='Reviewed at (DateTimeField).')
    final_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='final_reviewed_loan_origination_applications',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    final_reviewed_at = models.DateTimeField(null=True, blank=True, db_comment='Final reviewed at (DateTimeField).')
    submitted_at = models.DateTimeField(null=True, blank=True, db_comment='Submitted at (DateTimeField).')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, db_comment='Created at (DateTimeField).')
    updated_at = models.DateTimeField(auto_now=True, db_comment='Updated at (DateTimeField).')

    class Meta:
        db_table = 'core_loanoriginationapplication'
        db_table_comment = 'Domain: origination. Purpose: Canonical, revision-controlled application captured by a field officer. Classification: authoritative_record. Source of truth: yes. Lifecycle: active. Retention: Retained with the owning business record according to its workflow policy. Parents: auth.User, core.JawabuCustomer, origination.LoanOriginationApplication, core.OperationalLocation, origination.OriginationProductDefinition, core.ProductVersion. Children: origination.LoanOriginationApplication, origination.OriginationApplicationDocument, origination.OriginationApplicationEvent, origination.OriginationCommercialException, origination.OriginationCorrectionRequest, origination.OriginationReportingValue. Code usage: owning Django model and workflow service.'
        ordering = ['-updated_at']
        constraints = [
            models.UniqueConstraint(
                fields=['officer', 'client_request_id'],
                condition=~models.Q(client_request_id=''),
                name='unique_origination_create_request_per_officer',
            ),
        ]
        indexes = [
            models.Index(
                fields=['officer', 'status', 'updated_at'], name='core_loanor_officer_3c905e_idx',
            ),
            models.Index(
                fields=['branch', 'status', 'updated_at'], name='core_loanor_branch_8c321c_idx',
            ),
        ]

    def __str__(self):
        return self.reference_number



class OriginationCommercialException(models.Model):
    """Immutable Superuser approval for exact policy mismatches on one revision."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    application = models.ForeignKey(
        LoanOriginationApplication, on_delete=models.PROTECT,
        related_name='commercial_exceptions',
    db_comment='Reference to core_loanoriginationapplication; deletion behavior: PROTECT.')
    application_revision = models.PositiveIntegerField(db_comment='Application revision (PositiveIntegerField).')
    product_version = models.ForeignKey(
        'core.ProductVersion', on_delete=models.PROTECT,
        related_name='origination_commercial_exceptions',
    db_comment='Reference to core_productversion; deletion behavior: PROTECT.')
    entered_terms_sha256 = models.CharField(max_length=64, db_comment='Entered terms sha256 (CharField).')
    expected_quote_sha256 = models.CharField(max_length=64, db_comment='Expected quote sha256 (CharField).')
    covered_mismatch_codes = models.JSONField(default=list, db_comment='Covered mismatch codes (JSONField).')
    reason = models.TextField(db_comment='Reason (TextField).')
    approval_reference = models.CharField(max_length=255, db_comment='Approval reference (CharField).')
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='approved_origination_commercial_exceptions',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    approved_at = models.DateTimeField(default=timezone.now, db_index=True, db_comment='Approved at (DateTimeField).')

    class Meta:
        db_table = 'core_originationcommercialexception'
        db_table_comment = 'Domain: origination. Purpose: Immutable Superuser approval for exact policy mismatches on one revision. Classification: authoritative_record. Source of truth: yes. Lifecycle: active. Retention: Retained with the owning business record according to its workflow policy. Parents: auth.User, origination.LoanOriginationApplication, core.ProductVersion. Children: none. Code usage: owning Django model and workflow service.'
        verbose_name = 'Origination commercial exception'
        verbose_name_plural = 'Origination commercial exceptions'
        ordering = ['-approved_at', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=[
                    'application', 'application_revision', 'entered_terms_sha256',
                    'expected_quote_sha256',
                ],
                name='unique_origination_commercial_exception',
            ),
        ]
        indexes = [
            models.Index(
                fields=['application', 'application_revision'],
                name='orig_comm_exception_rev_idx',
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.application_id and self.product_version_id:
            if self.application.product_version_id != self.product_version_id:
                errors['product_version'] = 'The exception must use the application product version.'
        if self.approved_by_id and (
            not self.approved_by.is_active or not self.approved_by.is_superuser
        ):
            errors['approved_by'] = 'Only an active Django Superuser may approve this exception.'
        codes = self.covered_mismatch_codes or []
        if not isinstance(codes, list) or not codes or any(not isinstance(item, str) for item in codes):
            errors['covered_mismatch_codes'] = 'At least one stable policy mismatch code is required.'
        if not str(self.reason or '').strip():
            errors['reason'] = 'Record why this exception was approved.'
        if not str(self.approval_reference or '').strip():
            errors['approval_reference'] = 'Record the external approval reference.'
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Origination commercial exceptions are append-only.')
        self.covered_mismatch_codes = sorted(set(self.covered_mismatch_codes or []))
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Origination commercial exceptions cannot be deleted.')

    def __str__(self):
        return f'{self.application.reference_number} r{self.application_revision}'



class OriginationReportingValue(models.Model):
    """Rebuildable typed projection of explicitly reportable application values."""

    id = models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID',
                             db_comment='Immutable reporting-projection row identifier.')

    application = models.ForeignKey(
        LoanOriginationApplication, on_delete=models.CASCADE,
        related_name='reporting_values',
    db_comment='Reference to core_loanoriginationapplication; deletion behavior: CASCADE.')
    data_field = models.ForeignKey(
        OriginationDataField, on_delete=models.PROTECT,
        related_name='reporting_values',
    db_comment='Reference to core_originationdatafield; deletion behavior: PROTECT.')
    field_key = models.CharField(max_length=120, db_comment='Field key (CharField).')
    value_type = models.CharField(max_length=20, choices=OriginationDataField.TYPE_CHOICES, db_comment='Value type (CharField).')
    sensitivity = models.CharField(
        max_length=20, choices=OriginationDataField.SENSITIVITY_CHOICES,
    db_comment='Sensitivity (CharField).')
    masking_policy = models.CharField(
        max_length=16, choices=OriginationDataField.MASK_CHOICES,
    db_comment='Masking policy (CharField).')
    reporting_use = models.CharField(
        max_length=16, choices=OriginationDataField.REPORT_CHOICES,
    db_comment='Reporting use (CharField).')
    export_allowed = models.BooleanField(default=False, db_comment='Export allowed (BooleanField).')
    text_value = models.CharField(max_length=500, null=True, blank=True, db_comment='Text value (CharField).')
    decimal_value = models.DecimalField(
        max_digits=24, decimal_places=4, null=True, blank=True,
    db_comment='Decimal value (DecimalField).')
    date_value = models.DateField(null=True, blank=True, db_comment='Date value (DateField).')
    boolean_value = models.BooleanField(null=True, blank=True, db_comment='Boolean value (BooleanField).')
    choice_code = models.CharField(max_length=120, null=True, blank=True, db_comment='Choice code (CharField).')
    projected_at = models.DateTimeField(auto_now=True, db_comment='Projected at (DateTimeField).')

    class Meta:
        db_table = 'core_originationreportingvalue'
        db_table_comment = 'Domain: origination. Purpose: Rebuildable typed projection of explicitly reportable application values. Classification: authoritative_record. Source of truth: yes. Lifecycle: active. Retention: Retained with the owning business record according to its workflow policy. Parents: origination.LoanOriginationApplication, origination.OriginationDataField. Children: none. Code usage: owning Django model and workflow service.'
        ordering = ['application', 'field_key']
        constraints = [
            models.UniqueConstraint(
                fields=['application', 'data_field'],
                name='unique_origination_reporting_value',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(
                        value_type__in=['text', 'textarea', 'phone', 'national_id'],
                        text_value__isnull=False, decimal_value__isnull=True,
                        date_value__isnull=True, boolean_value__isnull=True,
                        choice_code__isnull=True,
                    )
                    | models.Q(
                        value_type__in=['number', 'money'], text_value__isnull=True,
                        decimal_value__isnull=False, date_value__isnull=True,
                        boolean_value__isnull=True, choice_code__isnull=True,
                    )
                    | models.Q(
                        value_type='date', text_value__isnull=True,
                        decimal_value__isnull=True, date_value__isnull=False,
                        boolean_value__isnull=True, choice_code__isnull=True,
                    )
                    | models.Q(
                        value_type='boolean', text_value__isnull=True,
                        decimal_value__isnull=True, date_value__isnull=True,
                        boolean_value__isnull=False, choice_code__isnull=True,
                    )
                    | models.Q(
                        value_type='choice', text_value__isnull=True,
                        decimal_value__isnull=True, date_value__isnull=True,
                        boolean_value__isnull=True, choice_code__isnull=False,
                    )
                ),
                name='orig_reporting_matching_typed_value',
            ),
        ]
        indexes = [
            models.Index(fields=['data_field', 'text_value'], name='orig_report_field_text_idx'),
            models.Index(fields=['data_field', 'decimal_value'], name='orig_report_field_num_idx'),
            models.Index(fields=['data_field', 'date_value'], name='orig_report_field_date_idx'),
            models.Index(fields=['data_field', 'boolean_value'], name='orig_report_field_bool_idx'),
            models.Index(fields=['data_field', 'choice_code'], name='orig_report_field_choice_idx'),
        ]

    def __str__(self):
        return f'{self.application.reference_number}: {self.field_key}'



class OriginationApplicationEvent(models.Model):
    """Append-only operational history for an origination application."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    application = models.ForeignKey(
        LoanOriginationApplication, on_delete=models.PROTECT, related_name='events',
    db_comment='Reference to core_loanoriginationapplication; deletion behavior: PROTECT.')
    action = models.CharField(max_length=80, db_index=True, db_comment='Action (CharField).')
    revision = models.PositiveIntegerField(db_comment='Revision (PositiveIntegerField).')
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='loan_origination_events',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    request_id = models.CharField(max_length=128, blank=True, default='', db_index=True, db_comment='Request id (CharField).')
    before_values = models.JSONField(default=dict, blank=True, db_comment='Before values (JSONField).')
    after_values = models.JSONField(default=dict, blank=True, db_comment='After values (JSONField).')
    metadata = models.JSONField(default=dict, blank=True, db_comment='Metadata (JSONField).')
    occurred_at = models.DateTimeField(default=timezone.now, db_index=True, db_comment='Occurred at (DateTimeField).')

    class Meta:
        db_table = 'core_originationapplicationevent'
        db_table_comment = 'Domain: origination. Purpose: Append-only operational history for an origination application. Classification: immutable_event. Source of truth: yes. Lifecycle: active. Retention: Retained with the permanent workflow or compliance audit record. Parents: auth.User, origination.LoanOriginationApplication. Children: none. Code usage: owning Django model and workflow service.'
        ordering = ['occurred_at', 'id']
        indexes = [models.Index(
            fields=['application', 'occurred_at'], name='core_origin_applica_ea7e72_idx',
        )]
        constraints = [
            models.UniqueConstraint(
                fields=['application', 'request_id'], condition=~models.Q(request_id=''),
                name='unique_origination_event_request',
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Origination application events are append-only.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Origination application events cannot be deleted.')



class OriginationReviewerNotice(models.Model):
    """Persistent in-app attention item for an Origination checker."""

    TYPE_APPROVAL_INVALIDATED = 'approval_invalidated'
    TYPE_CHOICES = [
        (TYPE_APPROVAL_INVALIDATED, 'Approval invalidated by officer recall'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    application = models.ForeignKey(
        LoanOriginationApplication, on_delete=models.PROTECT,
        related_name='reviewer_notices',
    db_comment='Reference to core_loanoriginationapplication; deletion behavior: PROTECT.')
    package = models.ForeignKey(
        'OriginationSigningPackage', null=True, blank=True, on_delete=models.PROTECT,
        related_name='reviewer_notices',
    db_comment='Reference to core_originationsigningpackage; deletion behavior: PROTECT.')
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='origination_reviewer_notices',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='created_origination_reviewer_notices',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    notice_type = models.CharField(max_length=32, choices=TYPE_CHOICES, db_index=True, db_comment='Notice type (CharField).')
    message = models.CharField(max_length=500, db_comment='Message (CharField).')
    request_id = models.CharField(max_length=128, db_comment='Request id (CharField).')
    seen_at = models.DateTimeField(null=True, blank=True, db_index=True, db_comment='Seen at (DateTimeField).')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, db_comment='Created at (DateTimeField).')

    class Meta:
        db_table = 'core_originationreviewernotice'
        db_table_comment = 'Domain: origination. Purpose: Persistent in-app attention item for an Origination checker. Classification: authoritative_record. Source of truth: yes. Lifecycle: active. Retention: Retained with the owning business record according to its workflow policy. Parents: auth.User, origination.LoanOriginationApplication, origination.OriginationSigningPackage. Children: none. Code usage: owning Django model and workflow service.'
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(
            fields=['application', 'recipient', 'request_id'],
            name='unique_orig_reviewer_notice_request',
        )]

    def __str__(self):
        return f'{self.application.reference_number}: {self.get_notice_type_display()}'



class OriginationCorrectionRequest(models.Model):
    """Append-preserving reviewer instructions for one submitted revision."""

    STATUS_OPEN = 'open'
    STATUS_ADDRESSED = 'addressed'
    STATUS_CHOICES = [
        (STATUS_OPEN, 'Open'),
        (STATUS_ADDRESSED, 'Addressed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    application = models.ForeignKey(
        LoanOriginationApplication, on_delete=models.PROTECT,
        related_name='correction_requests',
    db_comment='Reference to core_loanoriginationapplication; deletion behavior: PROTECT.')
    application_revision = models.PositiveIntegerField(db_comment='Application revision (PositiveIntegerField).')
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='origination_correction_requests',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    summary = models.TextField(max_length=2000, db_comment='Summary (TextField).')
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_OPEN, db_index=True,
    db_comment='Status (CharField).')
    addressed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='addressed_origination_corrections',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    addressed_at = models.DateTimeField(null=True, blank=True, db_comment='Addressed at (DateTimeField).')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, db_comment='Created at (DateTimeField).')

    class Meta:
        db_table = 'core_originationcorrectionrequest'
        db_table_comment = 'Domain: origination. Purpose: Append-preserving reviewer instructions for one submitted revision. Classification: authoritative_record. Source of truth: yes. Lifecycle: active. Retention: Retained with the owning business record according to its workflow policy. Parents: auth.User, origination.LoanOriginationApplication. Children: origination.OriginationCorrectionItem. Code usage: owning Django model and workflow service.'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['application', 'application_revision'],
                name='unique_orig_correction_revision',
            ),
        ]
        indexes = [models.Index(
            fields=['application', 'status', 'created_at'],
            name='orig_corr_app_status_idx',
        )]

    def __str__(self):
        return f'{self.application.reference_number} correction r{self.application_revision}'

    def delete(self, *args, **kwargs):
        raise ValidationError('Origination correction requests cannot be deleted.')



class OriginationCorrectionItem(models.Model):
    """Immutable field or requirement target within a correction request."""

    TARGET_FIELD = 'field'
    TARGET_REQUIREMENT = 'requirement'
    TARGET_DOCUMENT_FIELD = 'document_field'
    TARGET_SIGNATURE_SLOT = 'signature_slot'
    TARGET_CHOICES = [
        (TARGET_FIELD, 'Application field'),
        (TARGET_REQUIREMENT, 'Product requirement'),
        (TARGET_DOCUMENT_FIELD, 'Supporting-document field'),
        (TARGET_SIGNATURE_SLOT, 'Signature slot'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    correction_request = models.ForeignKey(
        OriginationCorrectionRequest, on_delete=models.PROTECT, related_name='items',
    db_comment='Reference to core_originationcorrectionrequest; deletion behavior: PROTECT.')
    target_type = models.CharField(max_length=20, choices=TARGET_CHOICES, db_comment='Target type (CharField).')
    target_key = models.CharField(max_length=240, db_comment='Target key (CharField).')
    target_label = models.CharField(max_length=160, db_comment='Target label (CharField).')
    instruction = models.CharField(max_length=1000, blank=True, default='', db_comment='Instruction (CharField).')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Created at (DateTimeField).')

    class Meta:
        db_table = 'core_originationcorrectionitem'
        db_table_comment = 'Domain: origination. Purpose: Immutable field or requirement target within a correction request. Classification: processing_record. Source of truth: yes. Lifecycle: active. Retention: Retained with the owning business record according to its workflow policy. Parents: origination.OriginationCorrectionRequest. Children: none. Code usage: owning Django model and workflow service.'
        ordering = ['created_at', 'id']
        constraints = [models.UniqueConstraint(
            fields=['correction_request', 'target_type', 'target_key'],
            name='unique_orig_correction_target',
        )]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Origination correction items are immutable.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Origination correction items cannot be deleted.')



class OriginationRequirementEvidence(models.Model):
    """Audited Drive-backed evidence for one snapshotted product requirement."""

    STATUS_PENDING = 'pending'
    STATUS_UPLOADED = 'uploaded'
    STATUS_FAILED = 'failed'
    STATUS_REMOVED = 'removed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending upload'),
        (STATUS_UPLOADED, 'Uploaded'),
        (STATUS_FAILED, 'Upload failed'),
        (STATUS_REMOVED, 'Removed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    application = models.ForeignKey(
        LoanOriginationApplication, on_delete=models.PROTECT,
        related_name='requirement_evidence_files',
    db_comment='Reference to core_loanoriginationapplication; deletion behavior: PROTECT.')
    application_revision = models.PositiveIntegerField(db_comment='Application revision (PositiveIntegerField).')
    requirement_key = models.CharField(max_length=80, db_comment='Requirement key (CharField).')
    requirement_label = models.CharField(max_length=160, db_comment='Requirement label (CharField).')
    original_filename = models.CharField(max_length=255, db_comment='Original filename (CharField).')
    mime_type = models.CharField(max_length=100, db_comment='Mime type (CharField).')
    byte_size = models.PositiveBigIntegerField(db_comment='Byte size (PositiveBigIntegerField).')
    content_sha256 = models.CharField(max_length=64, db_index=True, db_comment='Content sha256 (CharField).')
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True,
    db_comment='Status (CharField).')
    drive_file_id = models.CharField(max_length=255, blank=True, default='', db_comment='Drive file id (CharField).')
    drive_url = models.URLField(max_length=1000, blank=True, default='', db_comment='Drive url (CharField).')
    upload_error = models.TextField(blank=True, default='', db_comment='Upload error (TextField).')
    request_id = models.CharField(max_length=128, db_comment='Request id (CharField).')
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='uploaded_origination_requirement_evidence',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    removed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='removed_origination_requirement_evidence',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    removed_at = models.DateTimeField(null=True, blank=True, db_comment='Removed at (DateTimeField).')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, db_comment='Created at (DateTimeField).')
    updated_at = models.DateTimeField(auto_now=True, db_comment='Updated at (DateTimeField).')

    class Meta:
        db_table = 'core_originationrequirementevidence'
        db_table_comment = 'Domain: origination. Purpose: Audited Drive-backed evidence for one snapshotted product requirement. Classification: authoritative_record. Source of truth: yes. Lifecycle: active. Retention: Retained with the owning business record according to its workflow policy. Parents: auth.User, origination.LoanOriginationApplication. Children: none. Code usage: owning Django model and workflow service.'
        ordering = ['requirement_key', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['application', 'request_id'],
                name='unique_orig_evidence_request',
            ),
        ]
        indexes = [
            models.Index(
                fields=['application', 'requirement_key', 'status'],
                name='orig_evid_app_req_status_idx',
            ),
        ]

    def __str__(self):
        return f'{self.application.reference_number}: {self.requirement_label}'

    def delete(self, *args, **kwargs):
        raise ValidationError('Origination evidence cannot be deleted; remove it logically.')



class OriginationApplicationDocument(models.Model):
    """Application-scoped snapshot and progress for one generated packet document."""

    SOURCE_REQUIRED = 'required'
    SOURCE_RULE = 'rule'
    SOURCE_DEFAULT = 'default'
    SOURCE_OFFICER = 'officer'
    SOURCE_CHOICES = [
        (SOURCE_REQUIRED, 'Required'),
        (SOURCE_RULE, 'Applicability rule'),
        (SOURCE_DEFAULT, 'Default selection'),
        (SOURCE_OFFICER, 'Officer selection'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    application = models.ForeignKey(
        LoanOriginationApplication, on_delete=models.PROTECT, related_name='packet_documents',
    db_comment='Reference to core_loanoriginationapplication; deletion behavior: PROTECT.')
    template = models.ForeignKey(
        OriginationDocumentTemplate, null=True, blank=True, on_delete=models.PROTECT,
        related_name='application_documents',
    db_comment='Reference to core_originationdocumenttemplate; deletion behavior: PROTECT.')
    assignment = models.ForeignKey(
        OriginationProductDocumentAssignment, null=True, blank=True,
        on_delete=models.PROTECT, related_name='application_documents',
    db_comment='Reference to core_originationproductdocumentassignment; deletion behavior: PROTECT.')
    document_key = models.SlugField(max_length=80, db_comment='Document key (SlugField).')
    name = models.CharField(max_length=180, db_comment='Name (CharField).')
    document_role = models.CharField(max_length=16, choices=OriginationDocumentTemplate.ROLE_CHOICES, db_comment='Document role (CharField).')
    display_order = models.PositiveSmallIntegerField(default=0, db_comment='Display order (PositiveSmallIntegerField).')
    inclusion_mode = models.CharField(max_length=24, choices=OriginationDocumentTemplate.INCLUDE_CHOICES, db_comment='Inclusion mode (CharField).')
    selection_source = models.CharField(max_length=16, choices=SOURCE_CHOICES, default=SOURCE_REQUIRED, db_comment='Selection source (CharField).')
    applicable = models.BooleanField(default=True, db_comment='Applicable (BooleanField).')
    selected = models.BooleanField(default=True, db_comment='Selected (BooleanField).')
    template_snapshot = models.JSONField(default=dict, db_comment='Template snapshot (JSONField).')
    schema_snapshot = models.JSONField(default=dict, blank=True, db_comment='Schema snapshot (JSONField).')
    signer_rules_snapshot = models.JSONField(default=list, blank=True, db_comment='Signer rules snapshot (JSONField).')
    field_payload = models.JSONField(default=dict, blank=True, db_comment='Field payload (JSONField).')
    previewed_application_revision = models.PositiveIntegerField(null=True, blank=True, db_comment='Previewed application revision (PositiveIntegerField).')
    completed_at = models.DateTimeField(null=True, blank=True, db_comment='Completed at (DateTimeField).')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Created at (DateTimeField).')
    updated_at = models.DateTimeField(auto_now=True, db_comment='Updated at (DateTimeField).')

    class Meta:
        db_table = 'core_originationapplicationdocument'
        db_table_comment = 'Domain: origination. Purpose: Application-scoped snapshot and progress for one generated packet document. Classification: authoritative_record. Source of truth: yes. Lifecycle: active. Retention: Retained with the owning business record according to its workflow policy. Parents: origination.LoanOriginationApplication, origination.OriginationDocumentTemplate, origination.OriginationProductDocumentAssignment. Children: none. Code usage: owning Django model and workflow service.'
        ordering = ['display_order', 'document_key']
        constraints = [models.UniqueConstraint(
            fields=['application', 'document_key'], name='unique_origination_application_document',
        )]

    def __str__(self):
        return f'{self.application.reference_number}: {self.name}'



class OriginationConsentPolicyVersion(models.Model):
    """Immutable approved wording bound to a conditional signing packet."""

    STATUS_DRAFT = 'draft'
    STATUS_ACTIVE = 'active'
    STATUS_RETIRED = 'retired'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'), (STATUS_ACTIVE, 'Active'), (STATUS_RETIRED, 'Retired'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    version = models.CharField(max_length=32, unique=True, db_comment='Version (CharField).')
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default=STATUS_DRAFT, db_index=True, db_comment='Status (CharField).')
    packet_clause = models.TextField(db_comment='Packet clause (TextField).')
    signer_consent_text = models.TextField(db_comment='Signer consent text (TextField).')
    signer_completion_text = models.TextField(db_comment='Signer completion text (TextField).')
    resigning_text = models.TextField(db_comment='Resigning text (TextField).')
    content_sha256 = models.CharField(max_length=64, unique=True, editable=False, db_comment='Content sha256 (CharField).')
    approval_reference = models.CharField(max_length=160, db_comment='Approval reference (CharField).')
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='approved_origination_consent_policies',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    approved_at = models.DateTimeField(null=True, blank=True, db_comment='Approved at (DateTimeField).')
    retired_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='retired_origination_consent_policies',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    retired_at = models.DateTimeField(null=True, blank=True, db_comment='Retired at (DateTimeField).')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='created_origination_consent_policies',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Created at (DateTimeField).')

    class Meta:
        db_table = 'core_originationconsentpolicyversion'
        db_table_comment = 'Domain: origination. Purpose: Immutable approved wording bound to a conditional signing packet. Classification: authoritative_record. Source of truth: yes. Lifecycle: active. Retention: Retained with the owning business record according to its workflow policy. Parents: auth.User. Children: origination.OriginationDocumentTemplate, origination.OriginationSigningPackage. Code usage: owning Django model and workflow service.'
        ordering = ['-created_at']
        constraints = [models.UniqueConstraint(
            fields=['status'], condition=models.Q(status='active'),
            name='one_active_origination_consent_policy',
        )]

    def _content_hash(self):
        import hashlib
        import json
        content = {
            'version': self.version,
            'packet_clause': self.packet_clause,
            'signer_consent_text': self.signer_consent_text,
            'signer_completion_text': self.signer_completion_text,
            'resigning_text': self.resigning_text,
        }
        return hashlib.sha256(json.dumps(
            content, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
        ).encode('utf-8')).hexdigest()

    def clean(self):
        super().clean()
        if self.status == self.STATUS_ACTIVE and not (
            self.approval_reference.strip() and self.approved_by_id and self.approved_at
        ):
            raise ValidationError('An active consent policy requires recorded compliance approval.')
        if self.status == self.STATUS_RETIRED and not (self.retired_by_id and self.retired_at):
            raise ValidationError('A retired consent policy requires retirement audit details.')

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Origination consent policy versions are immutable.')
        self.content_sha256 = self._content_hash()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Origination consent policy versions cannot be deleted.')

    def __str__(self):
        return f'{self.version} ({self.status})'



class OriginationSigningPackage(models.Model):
    """Stable cross-system link from one frozen revision to e-signatures."""

    STATUS_PENDING = 'pending'
    STATUS_IN_PROGRESS = 'in_progress'
    STATUS_FULLY_SIGNED = 'fully_signed'
    STATUS_DECLINED = 'declined'
    STATUS_EXPIRED = 'expired'
    STATUS_CANCELLED = 'cancelled'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_IN_PROGRESS, 'In progress'),
        (STATUS_FULLY_SIGNED, 'Fully signed'),
        (STATUS_DECLINED, 'Declined'),
        (STATUS_EXPIRED, 'Expired'),
        (STATUS_CANCELLED, 'Cancelled'),
        (STATUS_FAILED, 'Failed'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    application = models.ForeignKey(
        LoanOriginationApplication, on_delete=models.PROTECT, related_name='signing_packages',
    db_comment='Reference to core_loanoriginationapplication; deletion behavior: PROTECT.')
    application_revision = models.PositiveIntegerField(db_comment='Application revision (PositiveIntegerField).')
    external_reference = models.CharField(max_length=80, unique=True, db_index=True, db_comment='External reference (CharField).')
    document_type = models.CharField(max_length=80, db_comment='Document type (CharField).')
    template_version = models.PositiveIntegerField(null=True, blank=True, db_comment='Template version (PositiveIntegerField).')
    template_sha256 = models.CharField(max_length=64, blank=True, default='', db_comment='Template sha256 (CharField).')
    template_configuration_snapshot = models.JSONField(default=dict, blank=True, db_comment='Template configuration snapshot (JSONField).')
    context_snapshot = models.JSONField(default=dict, db_comment='Context snapshot (JSONField).')
    participants_snapshot = models.JSONField(default=list, db_comment='Participants snapshot (JSONField).')
    requirement_evidence_snapshot = models.JSONField(default=list, blank=True, db_comment='Requirement evidence snapshot (JSONField).')
    document_manifest_snapshot = models.JSONField(default=list, blank=True, db_comment='Document manifest snapshot (JSONField).')
    combined_document_hash = models.CharField(max_length=64, blank=True, default='', db_comment='Combined document hash (CharField).')
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True, db_comment='Status (CharField).')
    frozen_unsigned_document = models.BinaryField(blank=True, default=bytes, editable=False, db_comment='Frozen unsigned document (BinaryField).')
    unsigned_document_hash = models.CharField(max_length=64, blank=True, default='', db_comment='Unsigned document hash (CharField).')
    review_scope_sha256 = models.CharField(max_length=64, blank=True, default='', db_index=True, db_comment='Review scope sha256 (CharField).')
    conditional_approval = models.BooleanField(default=False, db_index=True, db_comment='Conditional approval (BooleanField).')
    consent_policy = models.ForeignKey(
        OriginationConsentPolicyVersion, null=True, blank=True, on_delete=models.PROTECT,
        related_name='signing_packages',
    db_comment='Reference to core_originationconsentpolicyversion; deletion behavior: PROTECT.')
    consent_policy_snapshot = models.JSONField(default=dict, blank=True, db_comment='Consent policy snapshot (JSONField).')
    approved_unsigned_document_hash = models.CharField(max_length=64, blank=True, default='', db_comment='Approved unsigned document hash (CharField).')
    approved_review_scope_sha256 = models.CharField(max_length=64, blank=True, default='', db_comment='Approved review scope sha256 (CharField).')
    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='prepared_origination_review_packages',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    prepared_at = models.DateTimeField(null=True, blank=True, db_comment='Prepared at (DateTimeField).')
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='reviewed_origination_signing_packages',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    reviewed_at = models.DateTimeField(null=True, blank=True, db_comment='Reviewed at (DateTimeField).')
    final_reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='final_reviewed_origination_signing_packages',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    final_reviewed_at = models.DateTimeField(null=True, blank=True, db_comment='Final reviewed at (DateTimeField).')
    final_decision = models.CharField(max_length=24, blank=True, default='', db_comment='Final decision (CharField).')
    final_review_reason = models.TextField(blank=True, default='', db_comment='Final review reason (TextField).')
    final_approved_signed_document_hash = models.CharField(max_length=64, blank=True, default='', db_comment='Final approved signed document hash (CharField).')
    signed_document_hash = models.CharField(max_length=64, blank=True, default='', db_comment='Signed document hash (CharField).')
    final_document_reference = models.TextField(blank=True, default='', db_comment='Final document reference (TextField).')
    final_drive_file_id = models.CharField(max_length=255, blank=True, default='', db_comment='Final drive file id (CharField).')
    archive_status = models.CharField(
        max_length=24,
        choices=[
            ('not_ready', 'Not ready'),
            ('pending', 'Pending'),
            ('uploaded', 'Uploaded'),
            ('failed', 'Failed'),
        ],
        default='not_ready',
        db_index=True,
    db_comment='Archive status (CharField).')
    archive_error = models.TextField(blank=True, default='', db_comment='Archive error (TextField).')
    pending_signed_document = models.BinaryField(blank=True, default=bytes, editable=False, db_comment='Pending signed document (BinaryField).')
    finalized_at = models.DateTimeField(null=True, blank=True, db_comment='Finalized at (DateTimeField).')
    archived_at = models.DateTimeField(null=True, blank=True, db_comment='Archived at (DateTimeField).')
    remote_error = models.TextField(blank=True, default='', db_comment='Remote error (TextField).')
    test_mode = models.BooleanField(default=False, db_comment='Test mode (BooleanField).')
    test_completed_at = models.DateTimeField(null=True, blank=True, db_comment='Test completed at (DateTimeField).')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Created at (DateTimeField).')
    updated_at = models.DateTimeField(auto_now=True, db_comment='Updated at (DateTimeField).')

    class Meta:
        db_table = 'core_originationsigningpackage'
        db_table_comment = 'Domain: origination. Purpose: Stable cross-system link from one frozen revision to e-signatures. Classification: authoritative_record. Source of truth: yes. Lifecycle: active. Retention: Retained with the owning business record according to its workflow policy. Parents: auth.User, origination.LoanOriginationApplication, origination.OriginationConsentPolicyVersion. Children: origination.OriginationReviewerNotice, origination.OriginationSignerSession, origination.OriginationSigningAction. Code usage: owning Django model and workflow service.'
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['application', 'application_revision'],
                name='one_signing_package_per_origination_revision',
            ),
        ]
        indexes = [models.Index(
            fields=['application', 'status', 'updated_at'], name='core_origin_applica_3a6bd3_idx',
        )]

    def __str__(self):
        return self.external_reference



class OriginationStampAsset(models.Model):
    """Versioned, controlled PNG used only in calibrated stamp slots."""

    ENV_TEST = 'test'
    ENV_PRODUCTION = 'production'
    ENV_CHOICES = [(ENV_TEST, 'Test only'), (ENV_PRODUCTION, 'Production')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    name = models.CharField(max_length=160, db_comment='Name (CharField).')
    branch = models.ForeignKey(
        'core.OperationalLocation', null=True, blank=True, on_delete=models.PROTECT,
        limit_choices_to={'location_type': 'branch'}, related_name='origination_stamp_assets',
    db_comment='Reference to core_operationallocation; deletion behavior: PROTECT.')
    environment = models.CharField(max_length=16, choices=ENV_CHOICES, default=ENV_TEST, db_comment='Environment (CharField).')
    version = models.PositiveIntegerField(default=1, db_comment='Version (PositiveIntegerField).')
    image_png = models.BinaryField(editable=False, db_comment='Image png (BinaryField).')
    content_sha256 = models.CharField(max_length=64, db_index=True, db_comment='Content sha256 (CharField).')
    byte_size = models.PositiveIntegerField(db_comment='Byte size (PositiveIntegerField).')
    active = models.BooleanField(default=False, db_index=True, db_comment='Active (BooleanField).')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='created_origination_stamp_assets',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='activated_origination_stamp_assets',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    activated_at = models.DateTimeField(null=True, blank=True, db_comment='Activated at (DateTimeField).')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Created at (DateTimeField).')

    class Meta:
        db_table = 'core_originationstampasset'
        db_table_comment = 'Domain: origination. Purpose: Versioned, controlled PNG used only in calibrated stamp slots. Classification: authoritative_record. Source of truth: yes. Lifecycle: active. Retention: Retained with the owning business record according to its workflow policy. Parents: auth.User, core.OperationalLocation. Children: origination.OriginationSigningAction. Code usage: owning Django model and workflow service.'
        ordering = ['name', 'branch', '-version']
        constraints = [
            models.UniqueConstraint(
                fields=['name', 'environment', 'version'],
                condition=models.Q(branch__isnull=True),
                name='unique_global_origination_stamp_version',
            ),
            models.UniqueConstraint(
                fields=['name', 'branch', 'environment', 'version'],
                condition=models.Q(branch__isnull=False),
                name='unique_branch_origination_stamp_version',
            ),
        ]

    def __str__(self):
        scope = self.branch.name if self.branch_id else 'Organization'
        return f'{self.name} v{self.version} ({scope}, {self.environment})'



class OriginationSignerSession(models.Model):
    """Revocable bearer session for one signer of one immutable packet."""

    STATUS_PENDING = 'pending'
    STATUS_OTP_SENT = 'otp_sent'
    STATUS_VERIFIED = 'verified'
    STATUS_LOCKED = 'locked'
    STATUS_EXPIRED = 'expired'
    STATUS_CANCELLED = 'cancelled'
    STATUS_CHOICES = [
        (STATUS_PENDING, 'Pending'),
        (STATUS_OTP_SENT, 'OTP sent'),
        (STATUS_VERIFIED, 'Verified'),
        (STATUS_LOCKED, 'Locked'),
        (STATUS_EXPIRED, 'Expired'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]
    MODE_SELF_SERVICE = 'self_service'
    MODE_ASSISTED = 'assisted'
    MODE_CHOICES = [
        (MODE_SELF_SERVICE, 'Self service'),
        (MODE_ASSISTED, 'Assisted by staff'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    package = models.ForeignKey(
        OriginationSigningPackage, on_delete=models.PROTECT, related_name='signer_sessions',
    db_comment='Reference to core_originationsigningpackage; deletion behavior: PROTECT.')
    signer_role = models.CharField(max_length=80, db_comment='Signer role (CharField).')
    identity_snapshot = models.JSONField(default=dict, blank=True, db_comment='Identity snapshot (JSONField).')
    phone_normalized = models.CharField(max_length=16, blank=True, default='', db_comment='Phone normalized (CharField).')
    phone_hash = models.CharField(max_length=64, blank=True, default='', db_index=True, db_comment='Phone hash (CharField).')
    phone_last4 = models.CharField(max_length=4, blank=True, default='', db_comment='Phone last4 (CharField).')
    token_hash = models.CharField(max_length=64, unique=True, db_index=True, db_comment='Token hash (CharField).')
    token_expires_at = models.DateTimeField(db_index=True, db_comment='Token expires at (DateTimeField).')
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default=STATUS_PENDING, db_index=True, db_comment='Status (CharField).')
    access_mode = models.CharField(max_length=24, choices=MODE_CHOICES, default=MODE_SELF_SERVICE, db_comment='Access mode (CharField).')
    is_active = models.BooleanField(default=True, db_index=True, db_comment='Is active (BooleanField).')
    consent_version = models.CharField(max_length=32, blank=True, default='', db_comment='Consent version (CharField).')
    consented_at = models.DateTimeField(null=True, blank=True, db_comment='Consented at (DateTimeField).')
    reviewed_pages = models.JSONField(default=list, blank=True, db_comment='Reviewed pages (JSONField).')
    signature_capture = models.JSONField(default=dict, blank=True, db_comment='Signature capture (JSONField).')
    signature_capture_sha256 = models.CharField(max_length=64, blank=True, default='', db_comment='Signature capture sha256 (CharField).')
    verified_at = models.DateTimeField(null=True, blank=True, db_comment='Verified at (DateTimeField).')
    locked_until = models.DateTimeField(null=True, blank=True, db_comment='Locked until (DateTimeField).')
    invalidated_at = models.DateTimeField(null=True, blank=True, db_comment='Invalidated at (DateTimeField).')
    shared_phone_override_reason = models.TextField(blank=True, default='', db_comment='Shared phone override reason (TextField).')
    shared_phone_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='approved_origination_shared_phone_sessions',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    shared_phone_approved_at = models.DateTimeField(null=True, blank=True, db_comment='Shared phone approved at (DateTimeField).')
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='created_origination_signer_sessions',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    assisted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='assisted_origination_signer_sessions',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    request_id = models.CharField(max_length=128, blank=True, default='', db_comment='Request id (CharField).')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Created at (DateTimeField).')
    updated_at = models.DateTimeField(auto_now=True, db_comment='Updated at (DateTimeField).')

    class Meta:
        db_table = 'core_originationsignersession'
        db_table_comment = 'Domain: origination. Purpose: Revocable bearer session for one signer of one immutable packet. Classification: authoritative_record. Source of truth: yes. Lifecycle: temporary. Retention: Service-managed bounded retention; see the owning service and deployment settings. Parents: auth.User, origination.OriginationSigningPackage. Children: origination.OriginationOtpChallenge, origination.OriginationSigningAction, origination.OriginationSigningRequestEvent. Code usage: owning Django model and workflow service.'
        ordering = ['package', 'signer_role', '-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['package', 'signer_role'], condition=models.Q(is_active=True),
                name='one_active_origination_signer_session',
            ),
            models.UniqueConstraint(
                fields=['package', 'request_id'], condition=~models.Q(request_id=''),
                name='unique_origination_signer_session_request',
            ),
        ]

    def __str__(self):
        return f'{self.package.external_reference}: {self.signer_role}'



class OriginationOtpChallenge(models.Model):
    """Hashed, bounded OTP challenge; provider delivery never proves signing."""

    DELIVERY_PENDING = 'pending'
    DELIVERY_ACCEPTED = 'accepted'
    DELIVERY_DELIVERED = 'delivered'
    DELIVERY_FAILED = 'failed'
    DELIVERY_UNKNOWN = 'unknown'
    DELIVERY_CHOICES = [
        (DELIVERY_PENDING, 'Pending'),
        (DELIVERY_ACCEPTED, 'Accepted'),
        (DELIVERY_DELIVERED, 'Delivered'),
        (DELIVERY_FAILED, 'Failed'),
        (DELIVERY_UNKNOWN, 'Unknown'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    session = models.ForeignKey(
        OriginationSignerSession, on_delete=models.PROTECT, related_name='otp_challenges',
    db_comment='Reference to core_originationsignersession; deletion behavior: PROTECT.')
    code_hash = models.CharField(max_length=255, db_comment='Code hash (CharField).')
    binding_sha256 = models.CharField(max_length=64, db_comment='Binding sha256 (CharField).')
    provider_message_id = models.CharField(max_length=255, blank=True, default='', db_index=True, db_comment='Provider message id (CharField).')
    delivery_status = models.CharField(
        max_length=24, choices=DELIVERY_CHOICES, default=DELIVERY_PENDING, db_index=True,
    db_comment='Delivery status (CharField).')
    provider_status = models.CharField(max_length=80, blank=True, default='', db_comment='Provider status (CharField).')
    send_sequence = models.PositiveSmallIntegerField(db_comment='Send sequence (PositiveSmallIntegerField).')
    attempts_remaining = models.PositiveSmallIntegerField(default=5, db_comment='Attempts remaining (PositiveSmallIntegerField).')
    request_id = models.CharField(max_length=128, db_comment='Request id (CharField).')
    source_ip_hash = models.CharField(max_length=64, blank=True, default='', db_index=True, db_comment='Source ip hash (CharField).')
    expires_at = models.DateTimeField(db_index=True, db_comment='Expires at (DateTimeField).')
    verified_at = models.DateTimeField(null=True, blank=True, db_comment='Verified at (DateTimeField).')
    invalidated_at = models.DateTimeField(null=True, blank=True, db_comment='Invalidated at (DateTimeField).')
    last_attempt_at = models.DateTimeField(null=True, blank=True, db_comment='Last attempt at (DateTimeField).')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, db_comment='Created at (DateTimeField).')

    class Meta:
        db_table = 'core_originationotpchallenge'
        db_table_comment = 'Domain: origination. Purpose: Hashed, bounded OTP challenge; provider delivery never proves signing. Classification: processing_record. Source of truth: yes. Lifecycle: temporary. Retention: Service-managed bounded retention; see the owning service and deployment settings. Parents: origination.OriginationSignerSession. Children: none. Code usage: owning Django model and workflow service.'
        ordering = ['session', '-send_sequence']
        constraints = [
            models.UniqueConstraint(
                fields=['session', 'send_sequence'], name='unique_origination_otp_sequence',
            ),
            models.UniqueConstraint(
                fields=['session', 'request_id'], name='unique_origination_otp_request',
            ),
        ]

    def __str__(self):
        return f'{self.session} OTP {self.send_sequence}'



class OriginationSigningRequestEvent(models.Model):
    """Minimal append-only database throttle evidence for public signing writes."""

    ACTION_MUTATE = 'mutate'
    ACTION_SEND = 'send'
    ACTION_VERIFY = 'verify'
    ACTION_CHOICES = [
        (ACTION_MUTATE, 'Signer write'),
        (ACTION_SEND, 'OTP send'),
        (ACTION_VERIFY, 'OTP verification'),
    ]

    id = models.BigAutoField(primary_key=True, db_comment='Id (BigAutoField).')
    session = models.ForeignKey(
        OriginationSignerSession, null=True, blank=True, on_delete=models.CASCADE,
        related_name='request_events',
    db_comment='Reference to core_originationsignersession; deletion behavior: CASCADE.')
    action = models.CharField(max_length=16, choices=ACTION_CHOICES, db_index=True, db_comment='Action (CharField).')
    request_id = models.CharField(max_length=128, blank=True, default='', db_comment='Request id (CharField).')
    payload_digest = models.CharField(max_length=64, blank=True, default='', db_comment='Payload digest (CharField).')
    token_hash = models.CharField(max_length=64, blank=True, default='', db_index=True, db_comment='Token hash (CharField).')
    source_ip_hash = models.CharField(max_length=64, blank=True, default='', db_index=True, db_comment='Source ip hash (CharField).')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, db_comment='Created at (DateTimeField).')

    class Meta:
        db_table = 'core_originationsigningrequestevent'
        db_table_comment = 'Domain: origination. Purpose: Minimal append-only database throttle evidence for public signing writes. Classification: immutable_event. Source of truth: yes. Lifecycle: active. Retention: Retained with the permanent workflow or compliance audit record. Parents: origination.OriginationSignerSession. Children: none. Code usage: owning Django model and workflow service.'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['action', 'token_hash', 'created_at'], name='core_osre_token_created_idx'),
            models.Index(fields=['action', 'source_ip_hash', 'created_at'], name='core_osre_ip_created_idx'),
        ]
        constraints = [models.UniqueConstraint(
            fields=['session', 'action', 'request_id'], condition=~models.Q(request_id=''),
            name='unique_origination_signing_request_event',
        )]



class OriginationSigningAction(models.Model):
    """Append-only evidence for one simulated or provider-verified slot action."""

    TYPE_SIGNATURE = 'signature'
    TYPE_STAMP = 'stamp'
    TYPE_DATE_SIGNED = 'date_signed'
    TYPE_CHOICES = [
        (TYPE_SIGNATURE, 'Signature'), (TYPE_STAMP, 'Stamp'),
        (TYPE_DATE_SIGNED, 'Signing date'),
    ]
    MODE_TEST = 'test'
    MODE_VERIFIED = 'verified'
    MODE_CHOICES = [(MODE_TEST, 'Test simulation'), (MODE_VERIFIED, 'Verified production')]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    package = models.ForeignKey(
        OriginationSigningPackage, on_delete=models.PROTECT, related_name='actions',
    db_comment='Reference to core_originationsigningpackage; deletion behavior: PROTECT.')
    document_key = models.SlugField(max_length=80, db_comment='Document key (SlugField).')
    slot_key = models.SlugField(max_length=80, db_comment='Slot key (SlugField).')
    signer_role = models.CharField(max_length=80, db_comment='Signer role (CharField).')
    action_type = models.CharField(max_length=16, choices=TYPE_CHOICES, db_comment='Action type (CharField).')
    mode = models.CharField(max_length=16, choices=MODE_CHOICES, db_comment='Mode (CharField).')
    stamp_asset = models.ForeignKey(
        OriginationStampAsset, null=True, blank=True, on_delete=models.PROTECT,
        related_name='signing_actions',
    db_comment='Reference to core_originationstampasset; deletion behavior: PROTECT.')
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT,
        related_name='origination_signing_actions',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    signer_session = models.ForeignKey(
        OriginationSignerSession, null=True, blank=True, on_delete=models.PROTECT,
        related_name='actions',
    db_comment='Reference to core_originationsignersession; deletion behavior: PROTECT.')
    supersedes = models.OneToOneField(
        'self', null=True, blank=True, on_delete=models.PROTECT,
        related_name='superseded_by',
    db_comment='Reference to core_originationsigningaction; deletion behavior: PROTECT.')
    request_id = models.CharField(max_length=128, db_index=True, db_comment='Request id (CharField).')
    metadata = models.JSONField(default=dict, blank=True, db_comment='Metadata (JSONField).')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True, db_comment='Created at (DateTimeField).')

    class Meta:
        db_table = 'core_originationsigningaction'
        db_table_comment = 'Domain: origination. Purpose: Append-only evidence for one simulated or provider-verified slot action. Classification: authoritative_record. Source of truth: yes. Lifecycle: active. Retention: Retained with the owning business record according to its workflow policy. Parents: auth.User, origination.OriginationSignerSession, origination.OriginationSigningAction, origination.OriginationSigningPackage, origination.OriginationStampAsset. Children: origination.OriginationSigningAction, origination.OriginationSigningActionInvalidation. Code usage: owning Django model and workflow service.'
        ordering = ['created_at', 'id']
        constraints = [
            models.UniqueConstraint(
                fields=['package', 'request_id'],
                name='unique_origination_signing_action_request',
            ),
        ]

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Origination signing actions are append-only.')
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Origination signing actions cannot be deleted.')



class OriginationSigningActionInvalidation(models.Model):
    """Append-only checker evidence invalidating one otherwise immutable action."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, db_comment='Id (UUIDField).')
    action = models.OneToOneField(
        OriginationSigningAction, on_delete=models.PROTECT, related_name='invalidation',
    db_comment='Reference to core_originationsigningaction; deletion behavior: PROTECT.')
    reason = models.CharField(max_length=1000, db_comment='Reason (CharField).')
    invalidated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name='invalidated_origination_signing_actions',
    db_comment='Reference to auth_user; deletion behavior: PROTECT.')
    request_id = models.CharField(max_length=128, unique=True, db_comment='Request id (CharField).')
    created_at = models.DateTimeField(auto_now_add=True, db_comment='Created at (DateTimeField).')

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError('Origination signature invalidations are append-only.')
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError('Origination signature invalidations cannot be deleted.')


    class Meta:
        db_table = 'core_originationsigningactioninvalidation'
        db_table_comment = 'Domain: origination. Purpose: Append-only checker evidence invalidating one otherwise immutable action. Classification: authoritative_record. Source of truth: yes. Lifecycle: active. Retention: Retained with the owning business record according to its workflow policy. Parents: auth.User, origination.OriginationSigningAction. Children: none. Code usage: owning Django model and workflow service.'

