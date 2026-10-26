import json
import logging
logger = logging.getLogger(__name__)
import re
import uuid
from django import forms
from core.admin import DOCUMENT_CONDITION_OPERATORS
from django.contrib import admin
from django.contrib import messages
from django.conf import settings
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.template.response import TemplateResponse
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, models, transaction
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils import timezone
from django.utils.text import slugify
from core.admin_deletion import TestingModelAdmin as ModelAdmin
from unfold.widgets import UnfoldAdminFileFieldWidget, UnfoldAdminSelectWidget
from urllib.parse import urlencode
from origination.models import (
    OriginationDataField,
    OriginationDataFieldEvent,
    OriginationProductDefinition,
    OriginationProductDefinitionEvent,
    OriginationDocumentTemplate,
    OriginationDocumentProductEligibility,
    OriginationDocumentTemplateEvent,
    OriginationTemplateConfigurationRevision,
    LoanOriginationApplication,
    OriginationCommercialException,
    OriginationReportingValue,
    OriginationApplicationEvent,
    OriginationCorrectionItem,
    OriginationCorrectionRequest,
    OriginationRequirementEvidence,
    OriginationApplicationDocument,
    OriginationConsentPolicyVersion,
    OriginationSigningParticipant,
    OriginationSigningPackage,
    OriginationSigningAction,
    OriginationSigningActionInvalidation,
    OriginationSignerSession,
    OriginationOtpChallenge,
    OriginationSigningRequestEvent,
    OriginationStampAsset,
)
from core.models import Product

from core.admin import (
    CompactModelAdmin,
    DocumentApplicabilityRuleFormMixin,
    _product_condition_fields,
    _simple_document_condition,
)


class OriginationProductDefinitionChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        terms_label = (
            f'terms v{obj.product_version.version}'
            if obj.product_version_id else 'legacy terms link'
        )
        return f'{obj.name} - loan form v{obj.version} ({terms_label})'


class OriginationDocumentTemplateForm(DocumentApplicabilityRuleFormMixin, forms.ModelForm):
    SCHEMA_PRESET_GENERIC_JAWABU_LAF = 'generic_jawabu_laf'

    # ModelForm's metaclass only collects declared fields from this concrete
    # class, so keep the visual-rule controls here as well as their shared
    # behaviour in the mixin.
    condition_field = forms.ChoiceField(
        required=False, label='Only include this document when',
        help_text='Leave as Always include unless this form is needed only for a particular application answer.',
        widget=UnfoldAdminSelectWidget,
    )
    condition_operator = forms.ChoiceField(
        required=False, choices=DOCUMENT_CONDITION_OPERATORS,
        label='Comparison', widget=UnfoldAdminSelectWidget,
    )
    condition_value = forms.CharField(
        required=False, label='Answer',
        help_text='Choose the answer that makes this document applicable.',
    )
    product_definition = OriginationProductDefinitionChoiceField(
        queryset=OriginationProductDefinition.objects.none(), required=False,
        empty_label='Reusable template library (not tied to one product)',
        label='Draft product (optional)',
        help_text=(
            'Choose a draft product only when this PDF belongs exclusively to it. '
            'Leave blank for a reusable LAF or supporting document that several products can share.'
        ),
        widget=UnfoldAdminSelectWidget,
    )
    reusable_family = forms.ChoiceField(
        required=False,
        label='Reusable template family',
        help_text=(
            'For a replacement PDF, choose the existing family so it becomes the next version. '
            'For a new reusable document, leave this on Create new family.'
        ),
        widget=UnfoldAdminSelectWidget,
    )
    schema_preset = forms.ChoiceField(
        required=False,
        label='Field setup',
        choices=(
            ('', 'Build fields visually after upload'),
            (SCHEMA_PRESET_GENERIC_JAWABU_LAF, 'Generic Jawabu LAF - reviewed two-page field set'),
        ),
        help_text=(
            'The reviewed preset creates or updates the canonical fields and signer roles automatically. '
            'No JSON or code entry is required.'
        ),
        widget=UnfoldAdminSelectWidget,
    )
    pdf_file = forms.FileField(
        help_text='Approved PDF. It is stored in the configured restricted Drive folder.',
        widget=UnfoldAdminFileFieldWidget,
    )
    native_consent_policy = forms.ModelChoiceField(
        queryset=OriginationConsentPolicyVersion.objects.none(), required=False,
        label='Consent clause embedded in this PDF',
        help_text=(
            'Select only when compliance has verified that this exact source PDF visibly contains '
            'the complete clause. Otherwise the governed notice page is prepended automatically.'
        ),
        widget=UnfoldAdminSelectWidget,
    )
    native_consent_attestation_reference = forms.CharField(
        required=False, max_length=160, label='Native-clause attestation reference',
        help_text='Required when an embedded consent policy is selected.',
    )
    eligible_products = forms.ModelMultipleChoiceField(
        queryset=Product.objects.none(), required=False,
        label='Available for products',
        help_text=(
            'Select every global product that may use this document. '
            'Leave all unchecked to keep it unavailable for new applications.'
        ),
        widget=forms.CheckboxSelectMultiple,
    )
    make_unavailable = forms.BooleanField(
        required=False, label='Publish without product availability',
        help_text='Use this to deliberately clear inherited eligibility on a replacement version.',
    )

    class Meta:
        model = OriginationDocumentTemplate
        fields = (
            'reusable_family', 'schema_preset', 'eligible_products', 'make_unavailable',
            'document_key', 'name', 'document_role',
            'inclusion_mode', 'display_order', 'officer_selectable',
            'default_selected', 'applicability_rule', 'form_schema',
            'signer_rules', 'pdf_file', 'native_consent_policy',
            'native_consent_attestation_reference',
        )
        widgets = {
            # These remain the audited storage format, but are authored through
            # the visual builder below rather than as hand-written JSON.
            'applicability_rule': forms.HiddenInput,
            'form_schema': forms.HiddenInput,
            'signer_rules': forms.HiddenInput,
            'document_key': forms.HiddenInput,
        }

    @staticmethod
    def eligible_product_definitions():
        return OriginationProductDefinition.objects.filter(
            lifecycle_status=OriginationProductDefinition.STATUS_DRAFT,
        ).select_related(
            'product_version', 'product_version__product',
        ).order_by('name', '-version')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop('product_definition', None)
        self.fields['eligible_products'].queryset = Product.objects.filter(active=True).order_by(
            'sort_order', 'name',
        )
        self.fields['native_consent_policy'].queryset = OriginationConsentPolicyVersion.objects.filter(
            status=OriginationConsentPolicyVersion.STATUS_ACTIVE,
        ).order_by('-approved_at')
        reusable_families = []
        seen_families = set()
        family_templates = OriginationDocumentTemplate.objects.filter(
            product_definition__isnull=True,
        ).exclude(
            status=OriginationDocumentTemplate.STATUS_UPLOAD_FAILED,
        ).order_by('document_type', '-version')
        for template in family_templates:
            if template.document_type in seen_families:
                continue
            seen_families.add(template.document_type)
            reusable_families.append((
                template.document_type,
                f'{template.name} - {template.get_document_role_display()} (current v{template.version})',
            ))
        self.fields['reusable_family'].choices = [
            ('', 'Create a new reusable family from the document name'),
            *reusable_families,
        ]
        defaults = {
            'document_key': 'primary',
            'document_role': OriginationDocumentTemplate.ROLE_PRIMARY,
            'inclusion_mode': OriginationDocumentTemplate.INCLUDE_REQUIRED,
            'display_order': 0,
            'officer_selectable': False,
            'default_selected': False,
            'applicability_rule': {},
            'form_schema': {},
            'signer_rules': [],
        }
        if not self.is_bound:
            for key, value in defaults.items():
                if key in self.fields:
                    self.fields[key].initial = value
        for key in defaults:
            if key in self.fields:
                self.fields[key].required = False
        self._configure_condition_editor()
        requested_family = str(
            (self.data.get('reusable_family') if self.is_bound else self.initial.get('reusable_family'))
            or ''
        ).strip()
        if requested_family and not self.is_bound:
            family_template = OriginationDocumentTemplate.objects.filter(
                product_definition__isnull=True, document_type=requested_family,
            ).exclude(status=OriginationDocumentTemplate.STATUS_UPLOAD_FAILED).order_by('-version').first()
            if family_template:
                self.fields['eligible_products'].initial = family_template.eligible_products.all()

    @staticmethod
    def _derived_family_key(name, role):
        key = slugify(str(name or '')).strip('-')[:80]
        if key:
            return key
        return 'shared-primary' if role == OriginationDocumentTemplate.ROLE_PRIMARY else 'shared-document'

    def clean(self):
        cleaned = super().clean()
        pdf_file = cleaned.get('pdf_file')
        product = None
        reusable_family = str(cleaned.get('reusable_family') or '').strip()
        schema_preset = str(cleaned.get('schema_preset') or '').strip()
        if not pdf_file:
            return cleaned
        cleaned['document_role'] = cleaned.get('document_role') or OriginationDocumentTemplate.ROLE_PRIMARY
        cleaned['inclusion_mode'] = cleaned.get('inclusion_mode') or OriginationDocumentTemplate.INCLUDE_REQUIRED
        cleaned['display_order'] = cleaned.get('display_order') or 0
        cleaned['officer_selectable'] = bool(cleaned.get('officer_selectable'))
        cleaned['default_selected'] = bool(cleaned.get('default_selected'))
        cleaned['applicability_rule'] = self._clean_condition_rule(cleaned)
        cleaned['form_schema'] = cleaned.get('form_schema') or {}
        cleaned['signer_rules'] = cleaned.get('signer_rules') or []
        native_policy = cleaned.get('native_consent_policy')
        native_reference = str(cleaned.get('native_consent_attestation_reference') or '').strip()
        if bool(native_policy) != bool(native_reference):
            self.add_error(
                'native_consent_attestation_reference',
                'Select the embedded consent policy and provide its attestation reference together.',
            )
        if not str(pdf_file.name).lower().endswith('.pdf'):
            self.add_error('pdf_file', 'Upload a PDF file.')
            return cleaned
        family_template = None
        if product and reusable_family:
            self.add_error('reusable_family', 'A product-owned PDF cannot also be placed in a reusable family.')
        if product and schema_preset:
            self.add_error(
                'schema_preset',
                'The Generic Jawabu LAF preset creates a reusable primary LAF. Leave Draft product blank.',
            )
        if reusable_family:
            family_template = OriginationDocumentTemplate.objects.filter(
                product_definition__isnull=True,
                document_type=reusable_family,
            ).exclude(
                status=OriginationDocumentTemplate.STATUS_UPLOAD_FAILED,
            ).order_by('-version').first()
            if not family_template:
                self.add_error('reusable_family', 'Choose an existing reusable template family.')
            elif not cleaned.get('eligible_products') and not cleaned.get('make_unavailable'):
                cleaned['eligible_products'] = family_template.eligible_products.all()

        role = cleaned['document_role']
        name = str(cleaned.get('name') or '').strip()
        if schema_preset == self.SCHEMA_PRESET_GENERIC_JAWABU_LAF:
            from origination.services.generic_jawabu_laf_seed import (
                DOCUMENT_NAME, DOCUMENT_TYPE, GenericJawabuLafSeedError,
                validate_catalogue_contract,
            )
            if reusable_family and reusable_family != DOCUMENT_TYPE:
                self.add_error('reusable_family', 'The reviewed preset belongs to the Generic Jawabu LAF family.')
            try:
                validate_catalogue_contract()
            except GenericJawabuLafSeedError as exc:
                self.add_error('schema_preset', str(exc))
            role = OriginationDocumentTemplate.ROLE_PRIMARY
            name = name or DOCUMENT_NAME
            document_type = DOCUMENT_TYPE
            family_template = OriginationDocumentTemplate.objects.filter(
                product_definition__isnull=True, document_type=DOCUMENT_TYPE,
            ).exclude(status=OriginationDocumentTemplate.STATUS_UPLOAD_FAILED).order_by('-version').first()
        elif family_template:
            role = family_template.document_role
            name = name or family_template.name
            document_type = family_template.document_type
        elif product:
            document_type = product.document_type if role == OriginationDocumentTemplate.ROLE_PRIMARY else ''
        else:
            document_type = self._derived_family_key(name, role)
            if OriginationDocumentTemplate.objects.filter(
                product_definition__isnull=True,
                document_type=document_type,
            ).exclude(status=OriginationDocumentTemplate.STATUS_UPLOAD_FAILED).exists():
                self.add_error(
                    'reusable_family',
                    'A reusable family with this name already exists. Select it above to upload its next version.',
                )

        if not name:
            self.add_error('name', 'Enter a clear document name.')
        if role == OriginationDocumentTemplate.ROLE_PRIMARY:
            document_key = 'primary'
        elif family_template:
            document_key = family_template.document_key
        else:
            document_key = self._derived_family_key(name, role)
        if product and role == OriginationDocumentTemplate.ROLE_SUPPORTING:
            document_type = f'{product.product_key}-{document_key}'[:80]
        cleaned.update({
            'name': name,
            'document_key': document_key,
            'document_role': role,
        })
        if role == OriginationDocumentTemplate.ROLE_PRIMARY:
            cleaned['inclusion_mode'] = OriginationDocumentTemplate.INCLUDE_REQUIRED
            cleaned['officer_selectable'] = False
        else:
            cleaned['inclusion_mode'] = OriginationDocumentTemplate.INCLUDE_OPTIONAL
            cleaned['officer_selectable'] = True
        cleaned['default_selected'] = False
        cleaned['applicability_rule'] = {}
        for key, value in cleaned.items():
            if key in self.fields and key not in {'eligible_products', 'make_unavailable'}:
                setattr(self.instance, key, value)
        if product and product.document_templates.exclude(
            status=OriginationDocumentTemplate.STATUS_UPLOAD_FAILED,
        ).filter(document_key=document_key).exists():
            self.add_error('product_definition', 'This draft product already has this document. Open its existing template instead.')
            return cleaned
        from origination.services.origination_templates import (
            OriginationTemplateError, initial_template_configuration, sample_context_for_schema,
            validate_template_pdf,
        )
        pdf_data = pdf_file.read()
        pdf_file.seek(0)
        try:
            digest, page_count = validate_template_pdf(pdf_data)
        except OriginationTemplateError as exc:
            raise forms.ValidationError(str(exc)) from exc
        if schema_preset == self.SCHEMA_PRESET_GENERIC_JAWABU_LAF and page_count != 2:
            self.add_error(
                'pdf_file',
                f'The reviewed Generic Jawabu LAF preset expects the two-page form; this PDF has {page_count} page(s).',
            )
        self.instance.product_definition = product
        self.instance.name = name
        self.instance.document_key = document_key
        self.instance.document_role = role
        self.instance.document_type = document_type
        self.instance.version = (
            product.version if product else
            (OriginationDocumentTemplate.objects.filter(document_type=self.instance.document_type)
             .aggregate(models.Max('version'))['version__max'] or 0) + 1
        )
        self.instance.source_filename = str(pdf_file.name)[:255]
        self.instance.source_sha256 = digest
        self.instance.source_byte_size = len(pdf_data)
        self.instance.page_count = page_count
        inherited_schema = family_template.form_schema if family_template else {}
        inherited_signers = family_template.signer_rules if family_template else []
        self.instance.placement_config = initial_template_configuration(
            product, form_schema=inherited_schema or None,
        )
        self.instance.placement_config['version'] = self.instance.version
        self.instance.placement_config['document_type'] = self.instance.document_type
        # Product-owned primaries use their product contract. Reusable family
        # successors inherit the family's governed schema and signer roles.
        self.instance.form_schema = (
            product.form_schema if role == OriginationDocumentTemplate.ROLE_PRIMARY and product
            else inherited_schema or cleaned.get('form_schema') or {}
        )
        self.instance.signer_rules = (
            product.signer_rules if role == OriginationDocumentTemplate.ROLE_PRIMARY and product
            else inherited_signers or cleaned.get('signer_rules') or []
        )
        sample_context = self.instance.placement_config.setdefault('sample_context', {})
        generated_samples = sample_context_for_schema(self.instance.form_schema)
        generated_canonical = generated_samples.pop('_canonical_values', {})
        for key, value in generated_samples.items():
            sample_context.setdefault(key, value)
        if generated_canonical:
            canonical_values = sample_context.setdefault('_canonical_values', {})
            for key, value in generated_canonical.items():
                canonical_values.setdefault(key, value)
        if role == OriginationDocumentTemplate.ROLE_SUPPORTING and not self.instance.form_schema:
            self.instance.form_schema = {'_revision': 0, 'sections': [], 'fields': []}
        from origination.services.origination_documents import validate_applicability_rule
        allowed_fields = {
            str(item.get('key')) for item in ((product.form_schema if product else {}) or {}).get('fields', [])
            if isinstance(item, dict) and item.get('key')
        }
        allowed_fields.update(
            str(item.get('key')) for item in (self.instance.form_schema or {}).get('fields', [])
            if isinstance(item, dict) and item.get('key')
        )
        try:
            validate_applicability_rule(
                cleaned.get('applicability_rule') or {}, allowed_fields=allowed_fields,
            )
        except ValueError as exc:
            self.add_error('applicability_rule', str(exc))
        self._pdf_data = pdf_data
        return cleaned


class OriginationGodModeAdminMixin:
    """Expose an explicit Superuser purge for Origination records only."""

    change_form_template = 'admin/core/origination_god_mode/change_form.html'

    def get_urls(self):
        return [
            path(
                '<path:object_id>/god-mode-purge/',
                self.admin_site.admin_view(self.origination_god_mode_purge_view),
                name=(
                    f'{self.model._meta.app_label}_{self.model._meta.model_name}'
                    '_god_mode_purge'
                ),
            ),
        ] + super().get_urls()

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        context = {**(extra_context or {})}
        if object_id and request.user.is_active and request.user.is_superuser:
            context['origination_god_mode_purge_url'] = reverse(
                'admin:'
                f'{self.model._meta.app_label}_{self.model._meta.model_name}'
                '_god_mode_purge',
                args=[object_id],
            )
        return super().changeform_view(request, object_id, form_url, context)

    def origination_god_mode_purge_view(self, request, object_id):
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied
        obj = self.get_object(request, object_id)
        if not obj:
            return HttpResponse(status=404)
        expected_confirmation = str(obj.pk)
        error = ''
        if request.method == 'POST':
            confirmation = str(request.POST.get('confirmation') or '').strip()
            reason = str(request.POST.get('reason') or '').strip()
            if confirmation != expected_confirmation:
                error = f'Type the exact record ID: {expected_confirmation}'
            elif not reason:
                error = 'Provide a reason for this permanent purge.'
            else:
                from origination.services.origination_god_mode import (
                    OriginationGodModeError, purge_origination_record,
                )
                try:
                    counts = purge_origination_record(
                        record=obj, actor=request.user, reason=reason,
                    )
                except OriginationGodModeError as exc:
                    error = str(exc)
                except Exception:
                    logger.exception(
                        'Origination God mode purge failed: model=%s object_id=%s actor_id=%s',
                        self.model._meta.label, object_id, request.user.pk,
                    )
                    error = 'The Origination purge failed. No database changes were committed.'
                else:
                    logger.warning(
                        'Origination God mode purge completed: model=%s object_id=%s '
                        'actor_id=%s reason=%r counts=%s drive_files_untouched=true',
                        self.model._meta.label, object_id, request.user.pk, reason[:500], counts,
                    )
                    summary = ', '.join(
                        f'{count} {label}' for label, count in counts.items()
                    ) or 'the selected record'
                    self.message_user(
                        request,
                        f'God mode purge completed: {summary}. Drive files were left untouched.',
                        level=messages.WARNING,
                    )
                    return HttpResponseRedirect(reverse(
                        f'admin:{self.model._meta.app_label}_{self.model._meta.model_name}_changelist',
                    ))
        elif request.method != 'GET':
            response = HttpResponse(status=405)
            response['Allow'] = 'GET, POST'
            return response
        from origination.services.origination_god_mode import preview_origination_purge
        return TemplateResponse(
            request,
            'admin/core/origination_god_mode/confirm_purge.html',
            {
                **self.admin_site.each_context(request),
                'opts': self.model._meta,
                'title': f'God mode purge: {self.model._meta.verbose_name}',
                'original': obj,
                'object_id': expected_confirmation,
                'error': error,
                'impact': preview_origination_purge(obj),
                'back_url': reverse(
                    f'admin:{self.model._meta.app_label}_{self.model._meta.model_name}_change',
                    args=[obj.pk],
                ),
            },
        )


class OriginationDataFieldAdminForm(forms.ModelForm):
    """Admin validation for controlled draft-only type corrections."""

    class Meta:
        model = OriginationDataField
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if 'data_type' in self.fields:
            self.fields['data_type'].help_text = (
                'Correctable while this field exists only in draft loan forms or ready '
                'templates. Once published or captured in an application, create a replacement '
                'field instead.'
            )
        if 'source_type' in self.fields:
            self.fields['source_type'].help_text = (
                'Governance changes apply to future application snapshots; existing applications '
                'keep their frozen contract.'
            )
        if 'help_text' in self.fields:
            self.fields['help_text'].help_text = (
                'Default guidance for future attachments. A product or document may keep its own '
                'presentation-specific guidance.'
            )

    def clean_data_type(self):
        data_type = self.cleaned_data['data_type']
        if not self.instance.pk:
            return data_type
        original = OriginationDataField.objects.filter(pk=self.instance.pk).first()
        if not original or original.data_type == data_type:
            return data_type
        from origination.services.origination_fields import data_field_type_change_blockers
        blockers = data_field_type_change_blockers(original)
        if blockers:
            raise forms.ValidationError(
                'This type is frozen because the field is used by '
                f"{', '.join(blockers)}. Create a correctly typed replacement field, or use the "
                'Origination testing reset before correcting this catalogue entry.'
            )
        return data_type

    def clean_choice_options(self):
        options = self.cleaned_data.get('choice_options') or []
        if not self.instance.pk:
            return options
        original = OriginationDataField.objects.filter(pk=self.instance.pk).values_list(
            'choice_options', flat=True,
        ).first() or []
        previous_codes = {
            str(item.get('code') or '') for item in original if isinstance(item, dict)
        }
        current_codes = {
            str(item.get('code') or '') for item in options if isinstance(item, dict)
        }
        removed = sorted(previous_codes - current_codes)
        if removed and self.cleaned_data.get('data_type') == OriginationDataField.TYPE_CHOICE:
            raise forms.ValidationError(
                'Canonical choice codes cannot be removed. Mark obsolete options inactive so '
                'historical values remain interpretable. Missing: ' + ', '.join(removed)
            )
        return options


@admin.register(OriginationDataField)
class OriginationDataFieldAdmin(OriginationGodModeAdminMixin, CompactModelAdmin):
    form = OriginationDataFieldAdminForm
    change_list_template = 'admin/core/originationdatafield/change_list.html'
    list_select_related = ('preferred_field',)
    list_display = (
        'key', 'label', 'data_type', 'category', 'source_type', 'sensitivity',
        'reporting_use', 'terminology_status', 'active', 'updated_at',
    )
    list_filter = (
        'active', 'data_type', 'source_type', 'sensitivity', 'reporting_use',
        'export_allowed', 'terminology_reviewed_distinct', 'category',
    )
    search_fields = ('key', 'label', 'category')
    readonly_fields = (
        'preferred_field', 'terminology_reviewed_distinct',
        'created_by', 'created_at', 'updated_at',
    )
    fieldsets = (
        ('Canonical identity', {
            'fields': (('key', 'label'), 'aliases', ('category', 'data_type')),
            'description': (
                'The stable key is locked after creation. A Superuser may correct the data type '
                'only while every use is still an editable draft; attached draft schemas are '
                'updated together.'
            ),
        }),
        ('Governance', {'fields': (
            ('source_type', 'sensitivity'), ('masking_policy', 'reporting_use'),
            ('export_allowed', 'active'),
            ('preferred_field', 'terminology_reviewed_distinct'),
        ), 'description': (
            'Editable governance for future applications. Every application already created keeps '
            'the governance values frozen in its schema snapshot.'
        )}),
        ('Input contract', {
            'fields': ('help_text', 'choice_options'),
            'description': (
                'Edit default guidance and choice labels for future configuration. Existing '
                'product-specific labels, rules, and application snapshots are preserved.'
            ),
        }),
        ('Field meaning (advanced)', {'fields': ('value_contract',), 'classes': ('collapse',),
            'description': 'Subject, ownership and reviewed value source. Existing application and published document meanings are locked.'}),
        ('Audit', {'fields': (('created_by', 'created_at'), 'updated_at'), 'classes': ('collapse',)}),
    )

    @admin.display(description='Terminology')
    def terminology_status(self, obj):
        if obj.preferred_field_id:
            return f'Legacy → {obj.preferred_field.key}'
        if obj.terminology_reviewed_distinct:
            return 'Confirmed distinct'
        return 'Preferred'

    def get_urls(self):
        return [
            path(
                'terminology-audit/',
                self.admin_site.admin_view(self.terminology_audit_view),
                name='origination_originationdatafield_terminology_audit',
            ),
        ] + super().get_urls()

    def terminology_audit_view(self, request):
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied
        from origination.services.origination_fields import (
            OriginationFieldError,
            consolidate_data_field,
            mark_data_field_terminology_distinct,
            terminology_audit_candidates,
        )
        if request.method == 'POST':
            try:
                action = str(request.POST.get('action') or '')
                if action == 'consolidate':
                    duplicate = OriginationDataField.objects.get(pk=request.POST.get('duplicate_id'))
                    preferred = OriginationDataField.objects.get(pk=request.POST.get('preferred_id'))
                    consolidate_data_field(
                        duplicate=duplicate, preferred=preferred, actor=request.user,
                    )
                    messages.success(
                        request,
                        f'{duplicate.label} is now a historical alias of {preferred.label}. '
                        'Existing applications and PDF mappings were left unchanged.',
                    )
                elif action == 'distinct':
                    data_field = OriginationDataField.objects.get(pk=request.POST.get('field_id'))
                    mark_data_field_terminology_distinct(
                        data_field=data_field, actor=request.user,
                    )
                    messages.success(request, f'{data_field.label} was confirmed as a distinct concept.')
                else:
                    raise OriginationFieldError('Choose a terminology review action.')
            except (OriginationDataField.DoesNotExist, OriginationFieldError, ValidationError) as exc:
                messages.error(request, str(exc))
            return HttpResponseRedirect(
                reverse('admin:origination_originationdatafield_terminology_audit'),
            )
        from origination.services.origination_terminology import ORIGINATION_TERMINOLOGY
        context = {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': 'Origination terminology audit',
            'candidates': terminology_audit_candidates(),
            'terminology': ORIGINATION_TERMINOLOGY,
        }
        return TemplateResponse(
            request, 'admin/core/originationdatafield/terminology_audit.html', context,
        )

    def save_model(self, request, obj, form, change):
        before = None
        if change:
            before = OriginationDataField.objects.filter(pk=obj.pk).values(
                'label', 'aliases', 'category', 'data_type', 'source_type',
                'sensitivity', 'masking_policy',
                'reporting_use', 'export_allowed', 'help_text', 'choice_options', 'active',
                'preferred_field_id', 'terminology_reviewed_distinct',
            ).first()
        if not obj.created_by_id:
            obj.created_by = request.user
        correction = None
        if before and before['data_type'] != obj.data_type:
            from origination.services.origination_fields import correct_draft_data_field_type
            correction = correct_draft_data_field_type(
                data_field=obj, new_type=obj.data_type,
                choice_options=obj.choice_options, structure_schema=obj.structure_schema,
                actor=request.user,
            )
        super().save_model(request, obj, form, change)
        after = {
            'label': obj.label, 'aliases': obj.aliases, 'category': obj.category,
            'data_type': obj.data_type, 'source_type': obj.source_type,
            'sensitivity': obj.sensitivity, 'masking_policy': obj.masking_policy,
            'reporting_use': obj.reporting_use, 'export_allowed': obj.export_allowed,
            'help_text': obj.help_text, 'choice_options': obj.choice_options,
            'active': obj.active,
            'preferred_field_id': obj.preferred_field_id,
            'terminology_reviewed_distinct': obj.terminology_reviewed_distinct,
        }
        action = 'created' if not change else ('deactivated' if before and before['active'] and not obj.active else 'updated')
        OriginationDataFieldEvent.objects.create(
            data_field=obj, action=action, actor=request.user,
            metadata={
                'key': obj.key, 'type': obj.data_type,
                'draft_contracts_updated': correction or {},
                'changed_fields': sorted(
                    key for key, value in after.items() if not before or before.get(key) != value
                ),
            },
        )

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj))
        if obj and 'key' not in fields:
            fields.append('key')
        return tuple(fields)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OriginationProductDefinition)
class OriginationProductDefinitionAdmin(OriginationGodModeAdminMixin, CompactModelAdmin):
    full_reset_confirmation = 'RESET ALL ORIGINATION DATA'
    change_list_template = 'admin/core/originationproductdefinition/change_list.html'
    list_display = (
        'product_key', 'name', 'version_state', 'template_readiness',
        'version_history_link', 'updated_at',
    )
    list_filter = ('lifecycle_status', 'is_active', 'document_type')
    search_fields = ('product_key', 'name', 'document_type')
    actions = ('create_new_version',)
    readonly_fields = (
        'version', 'document_type', 'document_template_name', 'document_template_version',
        'document_template_sha256', 'lifecycle_status', 'is_active', 'supersedes',
        'created_by', 'published_by', 'published_at', 'created_at', 'updated_at',
    )


    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                'setup/',
                self.admin_site.admin_view(self.setup_dashboard_view),
                name='origination_origination_setup_dashboard',
            ),
            path(
                'setup/start/',
                self.admin_site.admin_view(self.setup_start_view),
                name='origination_origination_setup_start',
            ),
            path(
                'setup/<path:object_id>/overview/',
                self.admin_site.admin_view(self.setup_detail_view),
                name='origination_origination_setup_detail',
            ),
            path(
                'setup/<path:object_id>/revise/',
                self.admin_site.admin_view(self.setup_revise_view),
                name='origination_origination_setup_revise',
            ),
            path(
                'setup/<path:object_id>/<slug:step_key>/',
                self.admin_site.admin_view(self.setup_step_view),
                name='origination_origination_setup_step',
            ),
            path(
                'setup/<path:object_id>/',
                self.admin_site.admin_view(self.setup_workspace_view),
                name='origination_origination_setup_workspace',
            ),
            path(
                'product-family/<path:product_key>/god-mode-purge/',
                self.admin_site.admin_view(self.product_family_purge_view),
                name='origination_originationproductdefinition_family_purge',
            ),
            path(
                'canonical-field/create/',
                self.admin_site.admin_view(self.create_canonical_field_view),
                name='origination_originationproductdefinition_create_canonical_field',
            ),
            path(
                'full-reset/',
                self.admin_site.admin_view(self.full_reset_view),
                name='origination_origination_full_reset',
            ),
            path(
                '<path:object_id>/upgrade-commercial-terms/',
                self.admin_site.admin_view(self.upgrade_commercial_terms_view),
                name='origination_originationproductdefinition_upgrade_commercial_terms',
            ),
            path(
                '<path:object_id>/create-next-version/',
                self.admin_site.admin_view(self.create_next_version_view),
                name='origination_originationproductdefinition_create_next_version',
            ),
            path(
                '<path:object_id>/version-history/',
                self.admin_site.admin_view(self.version_history_view),
                name='origination_originationproductdefinition_version_history',
            ),
        ]
        return custom + urls

    def setup_dashboard_view(self, request):
        from origination.origination_setup_admin import dashboard_view
        return dashboard_view(self, request)

    def setup_start_view(self, request):
        from origination.origination_setup_admin import start_view
        return start_view(self, request)

    def setup_detail_view(self, request, object_id):
        from origination.origination_setup_admin import detail_view
        return detail_view(self, request, object_id)

    def setup_workspace_view(self, request, object_id):
        from origination.origination_setup_admin import workspace_view
        return workspace_view(self, request, object_id)

    def setup_revise_view(self, request, object_id):
        from origination.origination_setup_admin import revise_view
        return revise_view(self, request, object_id)

    def setup_step_view(self, request, object_id, step_key):
        from origination.origination_setup_admin import step_view
        return step_view(self, request, object_id, step_key)

    def product_family_purge_view(self, request, product_key):
        if (
            not getattr(settings, 'ORIGINATION_PRODUCT_FAMILY_PURGE_ENABLED', False)
            or not request.user.is_active
            or not request.user.is_superuser
        ):
            raise PermissionDenied
        from origination.services.origination_god_mode import (
            OriginationGodModeError,
            preview_product_family_purge,
            purge_origination_product_family,
        )
        family = OriginationProductDefinition.objects.filter(product_key=product_key).order_by('-version')
        latest = family.first()
        if not latest and request.method != 'POST':
            return HttpResponse(status=404)
        confirmation_text = f'PURGE PRODUCT FAMILY {product_key}'
        error = ''
        request_id = str(request.POST.get('request_id') or uuid.uuid4())
        if request.method == 'POST':
            if str(request.POST.get('confirmation') or '').strip() != confirmation_text:
                error = f'Type exactly: {confirmation_text}'
            elif not str(request.POST.get('reason') or '').strip():
                error = 'Provide a reason for this permanent purge.'
            else:
                try:
                    counts, replayed = purge_origination_product_family(
                        product_key=product_key,
                        actor=request.user,
                        reason=request.POST.get('reason') or '',
                        request_id=request_id,
                    )
                except OriginationGodModeError as exc:
                    error = str(exc)
                except Exception:
                    logger.exception('Origination product-family purge failed: key=%s actor_id=%s', product_key, request.user.pk)
                    error = 'The product-family purge failed. No database changes were committed.'
                else:
                    summary = ', '.join(f'{count} {label}' for label, count in counts.items()) or 'the product family'
                    self.message_user(
                        request,
                        f'{"Replayed" if replayed else "Completed"} Origination family purge: {summary}. Global Product records and Drive files were untouched.',
                        messages.WARNING,
                    )
                    return HttpResponseRedirect(reverse('admin:origination_originationproductdefinition_changelist'))
        elif request.method != 'GET':
            response = HttpResponse(status=405)
            response['Allow'] = 'GET, POST'
            return response
        return TemplateResponse(request, 'admin/core/origination_god_mode/family_purge.html', {
            **self.admin_site.each_context(request),
            'opts': self.model._meta,
            'title': f'Purge Origination product family: {product_key}',
            'original': latest,
            'product_key': product_key,
            'confirmation_text': confirmation_text,
            'impact': preview_product_family_purge(product_key),
            'error': error,
            'request_id': request_id,
            'back_url': (
                reverse('admin:origination_originationproductdefinition_change', args=[latest.pk])
                if latest else reverse('admin:origination_originationproductdefinition_changelist')
            ),
        })

    def create_canonical_field_view(self, request):
        """Create one governed input field without leaving an unsaved builder."""
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied
        if request.method != 'POST':
            response = JsonResponse({'ok': False, 'error': 'POST required.'}, status=405)
            response['Allow'] = 'POST'
            return response
        from origination.services.origination_fields import (
            OriginationFieldError,
            create_data_field,
            serialize_data_field,
        )
        try:
            body = json.loads(request.body or b'{}')
            if not isinstance(body, dict):
                raise ValidationError('Request body must be an object.')
            data_field, replayed = create_data_field(payload=body, actor=request.user)
            if not data_field.active:
                raise ValidationError(
                    'That canonical key already exists but is inactive. Reactivate it in Origination data fields.',
                )
            if data_field.source_type != OriginationDataField.SOURCE_USER_INPUT:
                raise ValidationError(
                    'That canonical key belongs to a system-derived field and cannot be added as officer input.',
                )
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JsonResponse({'ok': False, 'error': 'Request body must be valid JSON.'}, status=400)
        except OriginationFieldError as exc:
            return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
        except ValidationError as exc:
            return JsonResponse({'ok': False, 'error': '; '.join(exc.messages)}, status=400)
        return JsonResponse({
            'ok': True,
            'replayed': replayed,
            'field': serialize_data_field(data_field),
        })

    def full_reset_view(self, request):
        if (
            not getattr(settings, 'ORIGINATION_FULL_RESET_ENABLED', False)
            or not request.user.is_active
            or not request.user.is_superuser
        ):
            raise PermissionDenied

        from origination.services.origination_god_mode import (
            OriginationGodModeError,
            preview_full_origination_reset,
            reset_all_origination_data,
        )

        error = ''
        reason = str(request.POST.get('reason') or '').strip()
        confirmation = str(request.POST.get('confirmation') or '').strip()
        request_id = re.sub(
            r'[^A-Za-z0-9._-]', '',
            str(request.POST.get('request_id') or uuid.uuid4()),
        )[:128] or str(uuid.uuid4())
        if request.method == 'POST':
            if confirmation != self.full_reset_confirmation:
                error = f'Type the exact confirmation phrase: {self.full_reset_confirmation}'
            elif not reason:
                error = 'Provide a reason for this permanent reset.'
            elif len(reason) > 500:
                error = 'The reset reason must be 500 characters or fewer.'
            else:
                try:
                    result = reset_all_origination_data(
                        actor=request.user,
                        reason=reason,
                    )
                except OriginationGodModeError as exc:
                    error = str(exc)
                except Exception:
                    logger.exception(
                        'Origination full reset failed: actor_id=%s request_id=%s',
                        request.user.pk,
                        request_id,
                    )
                    error = 'The Origination reset failed. No database changes were committed.'
                else:
                    deleted_total = result['before']['total']
                    logger.warning(
                        'Origination full reset completed: actor_id=%s request_id=%s '
                        'reason=%r before_counts=%s deleted=%s after_counts=%s '
                        'drive_files_untouched=true',
                        request.user.pk,
                        request_id,
                        reason,
                        result['before']['counts'],
                        result['deleted'],
                        result['after']['counts'],
                    )
                    self.message_user(
                        request,
                        f'Origination reset complete. Deleted {deleted_total} database '
                        'record(s); Google Drive files and other workflows were untouched.',
                        level=messages.WARNING,
                    )
                    return HttpResponseRedirect(reverse('admin:origination_origination_full_reset'))
        elif request.method != 'GET':
            response = HttpResponse(status=405)
            response['Allow'] = 'GET, POST'
            return response

        preview = preview_full_origination_reset()
        return TemplateResponse(
            request,
            'admin/core/origination_god_mode/full_reset.html',
            {
                **self.admin_site.each_context(request),
                'opts': self.model._meta,
                'title': 'Reset all Origination data',
                'preview': preview,
                'confirmation_phrase': self.full_reset_confirmation,
                'confirmation': confirmation,
                'reason': reason,
                'request_id': request_id,
                'error': error,
                'back_url': reverse('admin:origination_originationproductdefinition_changelist'),
            },
        )

    def get_queryset(self, request):
        queryset = super().get_queryset(request).select_related(
            'created_by', 'published_by', 'supersedes',
        )
        resolver = getattr(request, 'resolver_match', None)
        if not resolver or resolver.url_name != 'origination_originationproductdefinition_changelist':
            return queryset
        latest_version = (
            OriginationProductDefinition.objects.filter(
                product_key=models.OuterRef('product_key'),
            )
            .order_by('-version')
            .values('version')[:1]
        )
        live_version = (
            OriginationProductDefinition.objects.filter(
                product_key=models.OuterRef('product_key'), is_active=True,
            )
            .values('version')[:1]
        )
        return queryset.annotate(
            _latest_version=models.Subquery(latest_version),
            _live_version=models.Subquery(live_version),
        ).filter(version=models.F('_latest_version'))

    @admin.display(description='Version state', ordering='version')
    def version_state(self, obj):
        live_version = getattr(obj, '_live_version', None)
        if obj.lifecycle_status == obj.STATUS_DRAFT:
            return (
                f'Draft v{obj.version} · Live v{live_version}'
                if live_version else f'Draft v{obj.version} · Not published'
            )
        if obj.is_active:
            return f'Published v{obj.version}'
        return f'{obj.get_lifecycle_status_display()} v{obj.version}'

    @admin.display(description='Versions')
    def version_history_link(self, obj):
        return format_html(
            '<a href="{}">Version history</a>',
            reverse(
                'admin:origination_originationproductdefinition_version_history',
                args=[obj.pk],
            ),
        )


    def upgrade_commercial_terms_view(self, request, object_id):
        if request.method != 'POST':
            response = HttpResponse(status=405)
            response['Allow'] = 'POST'
            return response
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied
        product_url = reverse('admin:origination_originationproductdefinition_change', args=[object_id])
        try:
            with transaction.atomic():
                product = OriginationProductDefinition.objects.select_for_update().filter(pk=object_id).first()
                if not product:
                    return HttpResponse(status=404)
                if product.lifecycle_status != product.STATUS_DRAFT:
                    raise ValidationError('Published product versions require an editable successor before Commercial Terms can change.')
                if not product.product_version_id:
                    raise ValidationError('This product is not linked to a governed ProductVersion.')
                from origination.services.origination_commercial_terms import (
                    COMMERCIAL_CONTRACT_VERSION, ensure_commercial_catalogue,
                    commercial_contract_version, merge_commercial_contract,
                )
                previous = commercial_contract_version(product.form_schema) or 1
                fields = ensure_commercial_catalogue(actor=request.user)
                upgraded = merge_commercial_contract(product.form_schema, fields=fields)
                if upgraded != product.form_schema:
                    product.form_schema = upgraded
                    product.save(update_fields=['form_schema', 'updated_at'])
                    product.document_templates.filter(
                        document_role=OriginationDocumentTemplate.ROLE_PRIMARY,
                        status__in=[OriginationDocumentTemplate.STATUS_READY, OriginationDocumentTemplate.STATUS_UPLOAD_FAILED],
                    ).update(form_schema=upgraded)
                    OriginationProductDefinitionEvent.objects.create(
                        product_definition=product, action='commercial_contract_upgraded',
                        actor=request.user, metadata={
                            'from_version': previous,
                            'contract_version': COMMERCIAL_CONTRACT_VERSION,
                            'source': 'django_admin',
                        },
                    )
        except (ValidationError, ValueError) as exc:
            error_message = ' '.join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
            self.message_user(request, error_message, level=messages.ERROR)
        else:
            self.message_user(
                request,
                'Commercial Terms upgraded. Officers now enter only loan amount and repayment tenor; policy values remain calculated.',
                level=messages.SUCCESS,
            )
        return HttpResponseRedirect(product_url)

    def _draft_packet_product(self, request, object_id):
        if not request.user.is_superuser:
            raise PermissionDenied
        product = OriginationProductDefinition.objects.filter(pk=object_id).first()
        if not product:
            return None
        if product.lifecycle_status != product.STATUS_DRAFT:
            raise ValidationError('Create an editable product version before changing its document packet.')
        return product

    @staticmethod
    def _packet_error_response(exc):
        from origination.services.origination_templates import OriginationTemplateError
        if isinstance(exc, (OriginationTemplateError, ValidationError)):
            return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
        logger.exception('Origination document-packet request failed.')
        return JsonResponse({'ok': False, 'error': 'The document-packet request could not be completed.'}, status=500)


    def add_view(self, request, form_url='', extra_context=None):
        if not self.has_add_permission(request):
            raise PermissionDenied
        return HttpResponseRedirect(reverse('admin:origination_origination_setup_dashboard'))

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        if not self.has_change_permission(request):
            raise PermissionDenied
        obj = self.get_object(request, object_id) if object_id else None
        if not obj:
            return HttpResponse(status=404)
        return HttpResponseRedirect(reverse('admin:origination_origination_setup_workspace', args=[obj.pk]))

    @admin.display(description='Template')
    def template_readiness(self, obj):
        from origination.services.origination_setup_documents import document_readiness
        if not obj.product_version_id:
            return 'Product terms required'
        documents, errors = document_readiness(obj)
        return errors[0] if errors else 'Published documents selected' if documents else 'Main LAF missing'

    @admin.action(description='Create editable next version')
    def create_new_version(self, request, queryset):
        if not request.user.is_superuser:
            raise PermissionDenied
        if queryset.count() != 1:
            self.message_user(request, 'Select exactly one product.', level=messages.ERROR)
            return None
        from origination.services.origination_templates import (
            OriginationTemplateError, clone_product_version,
        )
        try:
            clone = clone_product_version(queryset.first(), actor=request.user)
        except (OriginationTemplateError, ValidationError) as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return None
        except DatabaseError:
            logger.exception('Origination product successor creation failed.')
            self.message_user(
                request,
                'The editable version could not be created safely. Reload and try again.',
                level=messages.ERROR,
            )
            return None
        self.message_user(request, f'Product version {clone.version} is ready to edit.', level=messages.SUCCESS)
        return self._successor_response(clone)

    def _successor_response(self, successor):
        template = successor.document_templates.filter(
            status=OriginationDocumentTemplate.STATUS_READY,
            drive_file_id__gt='',
        ).order_by('-created_at').first()
        if template:
            return HttpResponseRedirect(reverse(
                'admin:origination_originationdocumenttemplate_calibrate', args=[template.pk],
            ))
        return HttpResponseRedirect(reverse(
            'admin:origination_originationproductdefinition_change', args=[successor.pk],
        ))

    def create_next_version_view(self, request, object_id):
        if not request.user.is_superuser:
            raise PermissionDenied
        if request.method != 'POST':
            response = HttpResponse(status=405)
            response['Allow'] = 'POST'
            return response
        source = OriginationProductDefinition.objects.filter(pk=object_id).first()
        if not source:
            return HttpResponse(status=404)
        if source.lifecycle_status != source.STATUS_PUBLISHED:
            self.message_user(
                request, 'Only a published product can create a successor.',
                level=messages.ERROR,
            )
            return HttpResponseRedirect(reverse(
                'admin:origination_originationproductdefinition_change', args=[source.pk],
            ))
        from origination.services.origination_templates import (
            OriginationTemplateError, clone_product_version,
        )
        try:
            successor = clone_product_version(source, actor=request.user)
        except (OriginationTemplateError, ValidationError) as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return HttpResponseRedirect(reverse(
                'admin:origination_originationproductdefinition_change', args=[source.pk],
            ))
        except DatabaseError:
            logger.exception(
                'Origination product successor creation failed.',
                extra={'product_definition_id': str(source.pk), 'user_id': request.user.pk},
            )
            self.message_user(
                request,
                'The editable version could not be created safely. Reload and try again.',
                level=messages.ERROR,
            )
            return HttpResponseRedirect(reverse(
                'admin:origination_originationproductdefinition_change', args=[source.pk],
            ))
        self.message_user(
            request,
            f'Editable version {successor.version} is ready with the existing PDF and alignment.',
            level=messages.SUCCESS,
        )
        return self._successor_response(successor)

    def version_history_view(self, request, object_id):
        if not request.user.is_superuser:
            raise PermissionDenied
        selected = OriginationProductDefinition.objects.filter(pk=object_id).first()
        if not selected:
            return HttpResponse(status=404)
        versions = list(
            OriginationProductDefinition.objects.filter(
                product_key=selected.product_key,
            ).select_related(
                'created_by', 'published_by', 'supersedes',
            ).prefetch_related('document_templates').order_by('-version')
        )
        rows = []
        for version in versions:
            templates = sorted(
                version.document_templates.all(),
                key=lambda candidate: candidate.created_at,
                reverse=True,
            )
            template = next((
                item for item in templates
                if item.status in [
                    OriginationDocumentTemplate.STATUS_READY,
                    OriginationDocumentTemplate.STATUS_ACTIVE,
                ]
            ), None)
            rows.append({
                'version': version,
                'template': template,
                'templates': [{
                    'template': item,
                    'change_url': reverse(
                        'admin:origination_originationdocumenttemplate_change',
                        args=[item.pk],
                    ),
                } for item in templates],
                'change_url': reverse(
                    'admin:origination_originationproductdefinition_change', args=[version.pk],
                ),
                'calibration_url': (
                    reverse(
                        'admin:origination_originationdocumenttemplate_calibrate',
                        args=[template.pk],
                    )
                    if template and version.lifecycle_status == version.STATUS_DRAFT
                    else ''
                ),
            })
        return TemplateResponse(
            request,
            'admin/core/originationproductdefinition/version_history.html',
            {
                **self.admin_site.each_context(request),
                'opts': self.model._meta,
                'title': f'{selected.name} version history',
                'selected': selected,
                'rows': rows,
                'changelist_url': reverse(
                    'admin:origination_originationproductdefinition_changelist',
                ),
            },
        )

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OriginationDocumentTemplate)
class OriginationDocumentTemplateAdmin(OriginationGodModeAdminMixin, CompactModelAdmin):
    form = OriginationDocumentTemplateForm
    change_form_template = 'admin/core/originationdocumenttemplate/change_form.html'
    change_list_template = 'admin/core/originationdocumenttemplate/change_list.html'
    list_display = ('name', 'document_role', 'eligible_products_summary', 'status', 'calibrate_link', 'page_count', 'updated_at')
    list_filter = ('status', 'document_role', 'inclusion_mode', 'document_type', 'product_definition')
    search_fields = ('name', 'document_type', 'source_filename', 'source_sha256')
    actions = ('activate_selected_templates', 'create_editable_selected_template')
    readonly_fields = (
        'product_definition', 'document_key', 'name', 'document_role', 'inclusion_mode',
        'display_order', 'officer_selectable', 'default_selected', 'applicability_summary',
        'eligible_products_summary',
        'configuration_summary', 'document_type', 'version', 'status', 'source_filename', 'source_sha256',
        'source_byte_size', 'page_count', 'calibration_link', 'drive_link',
        'native_consent_policy', 'native_consent_attestation_reference',
        'native_consent_attested_by', 'native_consent_attested_at',
        'published_configuration_revision', 'upload_error', 'created_by', 'activated_by',
        'activated_at', 'created_at', 'updated_at',
    )

    def get_queryset(self, request):
        return super().get_queryset(request).select_related(
            'product_definition', 'published_configuration_revision',
        ).prefetch_related('eligible_products')

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            # Values below are derived only after the PDF has been validated
            # and uploaded. Rendering all of them as blank readonly rows made
            # the add screen both misleading and unnecessarily tall.
            return ()
        return super().get_readonly_fields(request, obj)

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return ((
                'Upload PDF template',
                {
                    'description': (
                        'Upload an independent catalogue document and choose its eligible products. '
                        'Choose the reviewed Generic Jawabu LAF field setup when applicable; '
                        'otherwise define fields visually after upload. The alignment builder opens automatically.'
                    ),
                    'fields': (
                        'reusable_family', 'schema_preset', 'eligible_products', 'make_unavailable',
                        ('name', 'document_role'),
                        'display_order',
                        'applicability_rule', 'form_schema', 'signer_rules', 'pdf_file',
                        'native_consent_policy', 'native_consent_attestation_reference',
                    ),
                },
            ),)
        return (
            ('Template', {
                'fields': (
                    'product_definition', ('document_key', 'name'),
                    ('document_role', 'inclusion_mode', 'display_order'),
                    ('officer_selectable', 'default_selected'),
                    'eligible_products_summary',
                    'applicability_summary', 'configuration_summary',
                    ('document_type', 'version', 'status'),
                    'calibration_link',
                ),
            }),
            ('Source PDF', {
                'fields': (
                    'source_filename', ('source_byte_size', 'page_count'),
                    'source_sha256', 'drive_link', 'upload_error',
                ),
            }),
            ('Published calibration', {
                'description': 'Field positions, formatting, and signer slots are managed in the visual calibration builder.',
                'fields': ('published_configuration_revision',),
                'classes': ('collapse',),
            }),
            ('Consent clause', {
                'description': (
                    'If compliance attested that the governed clause is embedded in this exact source PDF, '
                    'conditional packets use it directly. Otherwise a governed first page is added before hashing.'
                ),
                'fields': (
                    'native_consent_policy', 'native_consent_attestation_reference',
                    ('native_consent_attested_by', 'native_consent_attested_at'),
                ),
                'classes': ('collapse',),
            }),
            ('Audit', {
                'fields': (
                    ('created_by', 'created_at'),
                    ('activated_by', 'activated_at'), 'updated_at',
                ),
                'classes': ('collapse',),
            }),
        )

    def changeform_view(self, request, object_id=None, form_url='', extra_context=None):
        context = {**(extra_context or {})}
        from origination.services.loan_origination import AUTHORING_SIGNER_ROLE_CATALOG as SIGNER_ROLE_CATALOG
        from origination.services.origination_fields import catalogue_for_product
        selected_product_id = request.POST.get('product_definition') or request.GET.get('product_definition')
        selected_product = OriginationProductDefinition.objects.filter(
            pk=selected_product_id,
        ).first() if selected_product_id else None
        context.update({
            'origination_signer_roles': [
                {'key': key, 'label': label} for key, label in SIGNER_ROLE_CATALOG
            ],
            'origination_data_fields': catalogue_for_product(selected_product),
            'origination_data_field_add_url': reverse('admin:origination_originationdatafield_add'),
            'origination_condition_fields_by_product': {
                str(item.pk): _product_condition_fields(item)
                for item in OriginationProductDefinition.objects.filter(
                    lifecycle_status=OriginationProductDefinition.STATUS_DRAFT,
                )
            },
        })
        if object_id is None:
            eligible_definitions = OriginationDocumentTemplateForm.eligible_product_definitions()
            context.update({
                'has_eligible_product_definitions': eligible_definitions.exists(),
                'create_product_definition_url': reverse(
                    'admin:origination_originationproductdefinition_add',
                ),
                'manage_product_definitions_url': reverse(
                    'admin:origination_originationproductdefinition_changelist',
                ),
            })
        else:
            original = self.get_object(request, object_id)
            if original:
                editable = OriginationDocumentTemplate.objects.filter(
                    product_definition__isnull=True,
                    document_type=original.document_type,
                    status=OriginationDocumentTemplate.STATUS_READY,
                    version__gt=original.version,
                ).order_by('-version').first()
                current = OriginationDocumentTemplate.objects.filter(
                    document_type=original.document_type,
                    status=OriginationDocumentTemplate.STATUS_ACTIVE,
                ).order_by('-version').first()
                context['origination_existing_editable_template'] = editable
                context['origination_current_family_template'] = current
                if original.status == original.STATUS_ACTIVE:
                    context['origination_create_editable_template_url'] = reverse(
                        'admin:origination_originationdocumenttemplate_create_editable_version',
                        args=[original.pk],
                    )
                context['origination_next_family_version_url'] = (
                    reverse('admin:origination_originationdocumenttemplate_add') + '?' + urlencode({
                        'reusable_family': original.document_type,
                        'name': original.name,
                    })
                )
                context['origination_attach_to_product_url'] = (
                    reverse('admin:origination_originationdocumenttemplate_calibrate', args=[original.pk])
                )
        return super().changeform_view(request, object_id, form_url, context)

    @admin.display(description='Inclusion condition')
    def applicability_summary(self, obj):
        rule = _simple_document_condition(obj.applicability_rule)
        if not rule:
            return 'Always included' if not obj.applicability_rule else 'Legacy multi-part condition retained'
        operator = dict(DOCUMENT_CONDITION_OPERATORS).get(rule['operator'], rule['operator'])
        value = '' if rule['operator'] in {'truthy', 'falsy'} else f' {rule.get("value", "")}'
        return f"{rule['field'].replace('_', ' ').title()} {operator}{value}"

    @admin.display(description='Available for products')
    def eligible_products_summary(self, obj):
        names = list(obj.eligible_products.order_by('sort_order', 'name').values_list('name', flat=True))
        return ', '.join(names) if names else 'No products assigned'

    @admin.display(description='Configured fields and signers')
    def configuration_summary(self, obj):
        schema = obj.form_schema if isinstance(obj.form_schema, dict) else {}
        fields = schema.get('fields') if isinstance(schema.get('fields'), list) else []
        sections = schema.get('sections') if isinstance(schema.get('sections'), list) else []
        signers = obj.signer_rules if isinstance(obj.signer_rules, list) else []
        return f'{len(fields)} field(s) in {len(sections)} section(s); {len(signers)} signer role(s).'

    def get_form(self, request, obj=None, **kwargs):
        if obj is not None:
            kwargs['form'] = forms.modelform_factory(
                OriginationDocumentTemplate, fields=(),
            )
        return super().get_form(request, obj, **kwargs)

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path('new-document/', self.admin_site.admin_view(self.document_new_view), name='origination_document_new'),
            path('<path:object_id>/edit-document/', self.admin_site.admin_view(self.document_edit_view), name='origination_document_edit'),
            path('<path:object_id>/editor-signers/', self.admin_site.admin_view(self.document_signers_view), name='origination_document_signers'),
            path('<path:object_id>/editor-readiness/', self.admin_site.admin_view(self.document_readiness_view), name='origination_document_readiness'),
            path(
                '<path:object_id>/create-editable-version/',
                self.admin_site.admin_view(self.create_editable_version_view),
                name='origination_originationdocumenttemplate_create_editable_version',
            ),
            path('<path:object_id>/calibrate/', self.admin_site.admin_view(self.calibrate_view), name='origination_originationdocumenttemplate_calibrate'),
            path('<path:object_id>/calibration-state/', self.admin_site.admin_view(self.calibration_state_view), name='origination_originationdocumenttemplate_calibration_state'),
            path('<path:object_id>/calibration-page/', self.admin_site.admin_view(self.calibration_page_view), name='origination_originationdocumenttemplate_calibration_page'),
            path('<path:object_id>/calibration-preview/', self.admin_site.admin_view(self.calibration_preview_view), name='origination_originationdocumenttemplate_calibration_preview'),
            path('<path:object_id>/calibration-save/', self.admin_site.admin_view(self.calibration_save_view), name='origination_originationdocumenttemplate_calibration_save'),
            path('<path:object_id>/calibration-field/', self.admin_site.admin_view(self.calibration_field_view), name='origination_originationdocumenttemplate_calibration_field'),
            path('<path:object_id>/calibration-publish/', self.admin_site.admin_view(self.calibration_publish_view), name='origination_originationdocumenttemplate_calibration_publish'),
        ]
        return custom + urls

    def document_new_view(self, request):
        from origination.document_editor_admin import new_view
        return new_view(self, request)

    def document_edit_view(self, request, object_id):
        from origination.document_editor_admin import edit_view
        return edit_view(self, request, object_id)

    def document_signers_view(self, request, object_id):
        from origination.document_editor_admin import write_view
        return write_view(self, request, object_id)

    def document_readiness_view(self, request, object_id):
        from origination.document_editor_admin import readiness_view
        return readiness_view(self, request, object_id)

    def create_editable_version_view(self, request, object_id):
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied
        if request.method != 'POST':
            response = HttpResponse(status=405)
            response['Allow'] = 'POST'
            return response
        source = OriginationDocumentTemplate.objects.filter(pk=object_id).first()
        if not source:
            return HttpResponse(status=404)
        from origination.services.origination_templates import (
            OriginationTemplateError, clone_reusable_template_version,
        )
        try:
            successor, replayed = clone_reusable_template_version(
                source, actor=request.user,
            )
        except OriginationTemplateError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return HttpResponseRedirect(reverse(
                'admin:origination_originationdocumenttemplate_change', args=[source.pk],
            ))
        except Exception:
            logger.exception('Creating an editable Origination template version failed.')
            self.message_user(
                request,
                'The editable version could not be created. No partial version was retained.',
                level=messages.ERROR,
            )
            return HttpResponseRedirect(reverse(
                'admin:origination_originationdocumenttemplate_change', args=[source.pk],
            ))
        self.message_user(
            request,
            (
                f'Opened existing editable version {successor.version}.'
                if replayed else
                f'Editable version {successor.version} is ready with the existing PDF, fields, and alignment.'
            ),
            level=messages.SUCCESS,
        )
        target = reverse('admin:origination_originationdocumenttemplate_calibrate', args=[successor.pk])
        setup_token = str(request.POST.get('setup_return') or '').strip()
        if setup_token:
            try:
                from origination.services.origination_setup import resolve_return_token
                from origination.services.origination_setup_documents import stage_change, selected_documents
                setup_target = resolve_return_token(setup_token)
                with transaction.atomic():
                    definition = OriginationProductDefinition.objects.select_for_update().get(pk=setup_target['definition_id'])
                    if not source.product_eligibilities.filter(product_id=definition.product_version.product_id).exists():
                        raise ValidationError('The document is not connected to this product.')
                    selected = list(selected_documents(definition))
                    if any(item.pk == source.pk for item in selected):
                        stage_change(definition=definition, action='edit', source=source, target=successor,
                            actor=request.user, request_id=f'editable-version:{successor.pk}')
                target += '?' + urlencode({'setup_return': setup_token})
            except (signing.BadSignature, ValidationError, OriginationProductDefinition.DoesNotExist):
                self.message_user(request, 'Return to product setup to choose this editable document.', level=messages.WARNING)
        return HttpResponseRedirect(target)

    def _calibration_template(self, request, object_id):
        if not request.user.is_superuser:
            raise PermissionDenied
        obj = self.get_object(request, object_id)
        if not obj:
            raise PermissionDenied
        return obj

    @admin.display(description='Alignment')
    def calibrate_link(self, obj):
        if not obj.drive_file_id:
            return 'Unavailable'
        url = reverse('admin:origination_originationdocumenttemplate_calibrate', args=[obj.pk])
        return format_html('<a href="{}">Calibrate fields</a>', url)

    @admin.display(description='Visual alignment editor')
    def calibration_link(self, obj):
        if not obj or not obj.pk or not obj.drive_file_id:
            return 'Available after the PDF is uploaded to Drive.'
        url = reverse('admin:origination_originationdocumenttemplate_calibrate', args=[obj.pk])
        return format_html(
            '<a class="button" style="display:inline-flex;background:#2563eb;color:#fff;'
            'padding:8px 14px;border-radius:7px;font-weight:700" href="{}">'
            'Open visual calibration</a>', url,
        )

    def calibrate_view(self, request, object_id):
        obj = self._calibration_template(request, object_id)
        product = obj.product_definition
        setup_return_url = ''
        setup_return_warning = ''
        setup_token = str(request.GET.get('setup_return') or '').strip()
        if setup_token:
            try:
                from origination.services.origination_setup import resolve_return_token
                setup_target = resolve_return_token(setup_token)
                setup_definition = OriginationProductDefinition.objects.filter(
                    pk=setup_target['definition_id'],
                ).first()
                owns_template = bool(
                    setup_definition
                    and (
                        obj.product_definition_id == setup_definition.pk
                        or obj.product_eligibilities.filter(product_id=setup_definition.product_version.product_id).exists()
                        or (product and product.pk == setup_definition.pk)
                    )
                )
                if not owns_template:
                    raise ValidationError('The PDF does not belong to that setup workspace.')
                setup_return_url = reverse(
                    'admin:origination_origination_setup_step',
                    args=[setup_definition.pk, setup_target['step_key']],
                )
            except (signing.BadSignature, ValidationError, ValueError):
                setup_return_url = reverse('admin:origination_origination_setup_dashboard')
                setup_return_warning = (
                    'The setup return link is invalid or expired. Saving is still safe; '
                    'Back returns to the product setup dashboard.'
                )
        return TemplateResponse(request, 'admin/core/originationdocumenttemplate/calibrate.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': f'Document: {obj.name}', 'template_record': obj,
            'editor_edit_url': reverse('admin:origination_document_edit', args=[obj.pk]),
            'calibration_create_editable_url': reverse(
                'admin:origination_originationdocumenttemplate_create_editable_version', args=[obj.pk],
            ) if obj.status == obj.STATUS_ACTIVE and obj.published_configuration_revision_id else '',
            'calibration_attach_product': product,
            'calibration_back_url': setup_return_url or (
                reverse('admin:origination_originationproductdefinition_change', args=[product.pk])
                if product else reverse('admin:origination_originationdocumenttemplate_changelist')
            ),
            'calibration_setup_return_url': setup_return_url,
            'calibration_setup_return_token': setup_token if setup_return_url and not setup_return_warning else '',
            'calibration_setup_return_warning': setup_return_warning,
            'calibration_attach_product_url': (
                reverse('admin:origination_originationdocumenttemplate_calibrate', args=[obj.pk])
                if obj.product_definition_id is None else ''
            ),
        })

    def calibration_state_view(self, request, object_id):
        obj = self._calibration_template(request, object_id)
        latest = obj.configuration_revisions.order_by('-revision').first()
        config = latest.configuration if latest else obj.placement_config
        from pypdf import PdfReader
        from io import BytesIO
        from origination.services.origination_templates import load_template_source
        reader = PdfReader(BytesIO(load_template_source(obj)))
        page_sizes = [{'page_number': i + 1, 'width': float(page.mediabox.width), 'height': float(page.mediabox.height)} for i, page in enumerate(reader.pages)]
        product = obj.product_definition or OriginationProductDefinition.objects.filter(
            document_type=obj.document_type, is_active=True,
        ).order_by('-version').first()
        from origination.services.origination_fields import (
            catalogue_for_product, product_schema_revision, template_owns_form_schema,
            template_schema_revision, template_form_contract,
        )
        owns_schema = template_owns_form_schema(obj)
        fields = (
            obj.form_schema
            if obj.form_schema and owns_schema
            else product.form_schema if product else {}
        )
        presentations = {
            str(item.get('key') or ''): item
            for item in (fields.get('fields') or [])
            if isinstance(item, dict) and item.get('key')
        }
        context_keys = catalogue_for_product(product)
        for item in context_keys:
            presentation = presentations.get(str(item.get('key') or ''), {})
            if owns_schema:
                item['attached'] = bool(presentation)
            item['required'] = bool(presentation.get('required', False))
            item['section_key'] = str(presentation.get('section_key') or '')
            item['label'] = presentation.get('label') or item['label']
            item['width'] = presentation.get('width', 'half')
            item['help_text'] = presentation.get('help_text', '')
            for metadata_key in ('value_contract', 'source_type', 'validation'):
                if metadata_key in presentation:
                    item[metadata_key] = presentation[metadata_key]
            if item.get('type') == OriginationDataField.TYPE_CHOICE and presentation.get('options'):
                item['choice_options'] = list(presentation['options'])
        from origination.services.origination_templates import _expected_signature_slots
        order = {key: index for index, key in enumerate(presentations)}
        context_keys.sort(key=lambda item: (order.get(item['key'], len(order)), item['label']))
        from origination.services.origination_value_contracts import annotate_form_fields
        from origination.services.origination_fields import template_form_contract
        context_keys = annotate_form_fields(context_keys, *template_form_contract(obj), primary=obj.document_role == 'primary',
                                           configuration=latest.configuration if latest else obj.placement_config)
        from origination.services.origination_templates import annotate_field_samples
        context_keys = annotate_field_samples(context_keys)
        samples = config.setdefault('sample_context', {})
        for field in context_keys:
            key = field['key']
            old = samples.get(key)
            # Repair recognizable old generated labels, not human examples.
            label_sample = old == field.get('label') or old == key.replace('_', ' ').title()
            typed_sample = field.get('type') not in {'text','textarea'} or (field.get('validation') or {}).get('format') == 'email'
            if old is None or label_sample and typed_sample or (
                field.get('type') in {'money','number'} and old == '12,500'
            ):
                samples[key] = field['sample_value']
                samples.setdefault('_canonical_values', {})[key] = field['sample_canonical_value']
        from origination.services.origination_setup_documents import shared_review
        from origination.services.document_editor import readiness, authoring_products
        from origination.services.loan_origination import AUTHORING_SIGNER_ROLE_CATALOG as SIGNER_ROLE_CATALOG
        return JsonResponse({
            'ok': True,
            'revision': latest.revision if latest else 0,
            'published': bool(latest and latest.is_published),
            'product_published': obj.status == obj.STATUS_ACTIVE or bool(obj.product_definition_id and product and product.is_active),
            'shared_review': shared_review(obj),
            'readiness': readiness(obj),
            'details':{'name':obj.name,'products':[str(pk) for pk in obj.eligible_products.values_list('pk',flat=True)],
                       'shared_values':fields.get('value_contract_version') == 2},
            'product_choices':list(authoring_products().order_by('name').values('id','name')),
            'signers': template_form_contract(obj)[1],
            'configuration': config,
            'page_sizes': page_sizes,
            'context_keys': context_keys,
            'schema_revision': template_schema_revision(obj) if owns_schema else product_schema_revision(product) if product else 0,
            'signer_roles': [(key, 'Officer' if key == 'officer' else label) for key, label in SIGNER_ROLE_CATALOG],
            'form_sections': list(fields.get('sections') or []),
            'signature_slots': list(_expected_signature_slots(product, obj).values()),
        })

    def calibration_page_view(self, request, object_id):
        obj = self._calibration_template(request, object_id)
        from origination.services.origination_templates import load_template_source
        from core.services.partnership_laf_preview import render_pdf_page
        try:
            content, total = render_pdf_page(load_template_source(obj), page_number=int(request.GET.get('page') or 1), scale=2)
        except Exception as exc:
            return self._calibration_error_response(exc)
        response = HttpResponse(content, content_type='image/jpeg')
        response['X-Preview-Page-Count'] = str(total)
        response['Cache-Control'] = 'private, no-store'
        return response

    def _json_body(self, request):
        try:
            return json.loads(request.body.decode('utf-8'))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValidationError('Invalid JSON request.')

    def _calibration_error_response(self, exc):
        from origination.services.origination_templates import OriginationTemplateError
        from origination.services.origination_fields import OriginationFieldError, OriginationFieldConflict
        if isinstance(exc, OriginationFieldConflict):
            return JsonResponse({'ok':False,'error':str(exc)}, status=409)
        if isinstance(exc, (OriginationTemplateError, OriginationFieldError, ValidationError)):
            return JsonResponse({'ok': False, 'error': str(exc)}, status=400)
        logger.exception('Origination template calibration request failed.')
        return JsonResponse({'ok': False, 'error': 'The calibration request could not be completed.'}, status=500)

    def calibration_preview_view(self, request, object_id):
        obj = self._calibration_template(request, object_id)
        if request.method != 'POST':
            return JsonResponse({'ok': False, 'error': 'POST required.'}, status=405)
        try:
            from origination.services.origination_templates import load_template_source, validate_template_configuration
            from core.services.partnership_laf_preview import render_pdf_page, render_template
            body = self._json_body(request)
            config = validate_template_configuration(
                body.get('configuration'), template=obj, require_complete=False,
            )
            sample_context = dict(config.get('sample_context') or {})
            sample_context['_show_signature_slots'] = True
            sample_context['_signature_appearance_version'] = 2
            pdf = render_template(load_template_source(obj), config, sample_context)
            content, total = render_pdf_page(pdf, page_number=int(body.get('page') or 1), scale=2)
        except Exception as exc:
            return self._calibration_error_response(exc)
        response = HttpResponse(content, content_type='image/jpeg')
        response['X-Preview-Page-Count'] = str(total)
        response['Cache-Control'] = 'private, no-store'
        return response

    def calibration_save_view(self, request, object_id):
        obj = self._calibration_template(request, object_id)
        if request.method != 'POST':
            return JsonResponse({'ok': False, 'error': 'POST required.'}, status=405)
        try:
            from origination.services.origination_templates import save_calibration_draft
            body = self._json_body(request)
            request_id = str(body.get('client_request_id') or request.headers.get('Idempotency-Key') or '')
            saved = save_calibration_draft(
                template=obj, configuration=body.get('configuration'), actor=request.user,
                expected_revision=int(body.get('revision')),
                client_request_id=request_id,
            )
        except Exception as exc:
            return self._calibration_error_response(exc)
        from origination.document_editor_admin import editor_data
        obj.refresh_from_db()
        return JsonResponse(editor_data(obj))

    def calibration_field_view(self, request, object_id):
        obj = self._calibration_template(request, object_id)
        if request.method != 'POST':
            return JsonResponse({'ok': False, 'error': 'POST required.'}, status=405)
        try:
            from origination.services.origination_fields import (
                attach_data_field, attach_data_field_to_template, catalogue_for_product,
                create_data_field, product_schema_revision, template_owns_form_schema,
                template_schema_revision,
            )
            body = self._json_body(request)
            if body.get('action') in {'update', 'remove', 'move_up', 'move_down'}:
                from origination.services.origination_fields import edit_template_field
                obj = edit_template_field(template=obj, key=str(body.get('field_key') or ''),
                    action=body['action'], presentation=body.get('presentation') or {}, actor=request.user,
                    expected_schema_revision=int(body.get('schema_revision') or 0),
                    configuration=body.get('configuration'), expected_revision=int(body.get('revision') or 0),
                    request_id=str(body.get('client_request_id') or ''))
                return self._edited_template_field_response(obj, body)
            with transaction.atomic():
                create_payload = body.get('create_field')
                if create_payload:
                    data_field, _replayed = create_data_field(
                        payload=create_payload, actor=request.user,
                    )
                else:
                    data_field = OriginationDataField.objects.filter(
                        pk=body.get('data_field_id'), active=True,
                    ).first()
                    if not data_field:
                        raise ValidationError('Choose an active canonical data field.')
                owns_schema = template_owns_form_schema(obj)
                if owns_schema:
                    obj, replayed = attach_data_field_to_template(
                        template=obj, data_field=data_field,
                        presentation=body.get('presentation') or {}, actor=request.user,
                        expected_schema_revision=int(body.get('schema_revision') or 0),
                    )
                    product = obj.product_definition
                elif obj.product_definition_id:
                    product, replayed = attach_data_field(
                        product=obj.product_definition, data_field=data_field,
                        presentation=body.get('presentation') or {}, actor=request.user,
                        expected_schema_revision=int(body.get('schema_revision') or 0),
                    )
                else:
                    raise ValidationError('A primary template must be linked to an editable product form.')
        except Exception as exc:
            return self._calibration_error_response(exc)
        context_keys = catalogue_for_product(product)
        presentations = {
            str(item.get('key') or ''): item
            for item in (((obj.form_schema if owns_schema else product.form_schema) or {}).get('fields') or [])
            if isinstance(item, dict) and item.get('key')
        }
        for item in context_keys:
            presentation = presentations.get(str(item.get('key') or ''), {})
            if owns_schema:
                item['attached'] = bool(presentation)
            item['required'] = bool(presentation.get('required', False))
            item['section_key'] = str(presentation.get('section_key') or '')
            if item.get('type') == OriginationDataField.TYPE_CHOICE and presentation.get('options'):
                item['choice_options'] = list(presentation['options'])
            for metadata_key in ('value_contract', 'source_type', 'validation'):
                if metadata_key in presentation:
                    item[metadata_key] = presentation[metadata_key]
        from origination.services.origination_templates import annotate_field_samples
        context_keys = annotate_field_samples(context_keys)
        return JsonResponse({
            'ok': True, 'field': next(
                item for item in context_keys if item['key'] == data_field.key
            ),
            'context_keys': context_keys,
            'schema_revision': template_schema_revision(obj) if owns_schema else product_schema_revision(product),
            'form_sections': list(((obj.form_schema if owns_schema else product.form_schema) or {}).get('sections') or []),
            'replayed': replayed,
        })

    def _edited_template_field_response(self, obj, body):
        from origination.services.origination_fields import catalogue_for_product, template_schema_revision
        from origination.services.origination_setup_documents import shared_review
        presentations = {field['key']: field for field in obj.form_schema.get('fields', [])}
        context_keys = catalogue_for_product(None)
        for field in context_keys:
            presentation = presentations.get(field['key'], {})
            field.update(attached=bool(presentation), required=bool(presentation.get('required')),
                         section_key=presentation.get('section_key', ''),
                         label=presentation.get('label') or field['label'],
                         help_text=presentation.get('help_text', ''), width=presentation.get('width', 'half'))
            for metadata_key in ('value_contract', 'source_type'):
                if metadata_key in presentation:
                    field[metadata_key] = presentation[metadata_key]
            if presentation.get('options'):
                field['choice_options'] = presentation['options']
        # Preserve document order while leaving unattached global choices searchable.
        order = {key: index for index, key in enumerate(presentations)}
        context_keys.sort(key=lambda item: (order.get(item['key'], len(order)), item['label']))
        from origination.services.origination_value_contracts import annotate_form_fields
        latest = obj.configuration_revisions.order_by('-revision').first()
        context_keys = annotate_form_fields(context_keys, obj.form_schema, obj.signer_rules, primary=obj.document_role == 'primary',
                                           configuration=latest.configuration if latest else obj.placement_config)
        from origination.services.origination_templates import annotate_field_samples
        context_keys = annotate_field_samples(context_keys)
        return JsonResponse({'ok':True, 'context_keys':context_keys, 'schema_revision':template_schema_revision(obj),
            'form_sections':obj.form_schema.get('sections', []), 'shared_review':shared_review(obj),
            'field':next((item for item in context_keys if item['key'] == body['field_key']), None),
            'configuration':latest.configuration if body['action'] == 'remove' and latest else None,
            'revision':latest.revision if latest else 0})

    def calibration_publish_view(self, request, object_id):
        obj = self._calibration_template(request, object_id)
        if request.method != 'POST':
            return JsonResponse({'ok': False, 'error': 'POST required.'}, status=405)
        try:
            from origination.services.document_editor import publish_document
            body = self._json_body(request)
            document = publish_document(document=obj, actor=request.user, revision=int(body.get('revision', 0)),
                request_id=str(body.get('client_request_id') or ''), impact_token=body.get('impact_token', ''))
            return JsonResponse({'ok': True, 'revision': document.published_configuration_revision.revision,
                                 'template_name': document.name})
        except Exception as exc:
            return self._calibration_error_response(exc)

    @admin.display(description='Drive file')
    def drive_link(self, obj):
        if not obj or not obj.drive_url:
            return 'Not uploaded'
        return format_html('<a href="{}" target="_blank" rel="noopener">Open approved PDF</a>', obj.drive_url)

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        if change:
            return
        obj.created_by = request.user
        obj.status = OriginationDocumentTemplate.STATUS_READY
        if obj.native_consent_policy_id:
            obj.native_consent_attested_by = request.user
            obj.native_consent_attested_at = timezone.now()
        schema_preset = str(form.cleaned_data.get('schema_preset') or '').strip()
        if schema_preset == OriginationDocumentTemplateForm.SCHEMA_PRESET_GENERIC_JAWABU_LAF:
            from origination.services.generic_jawabu_laf_seed import (
                SIGNER_RULES, build_form_schema, ensure_catalogue,
            )
            from origination.services.loan_origination import validate_product_form_contract
            from origination.services.origination_templates import initial_template_configuration

            fields = ensure_catalogue(actor=request.user)
            obj.form_schema = build_form_schema(fields)
            obj.signer_rules = json.loads(json.dumps(SIGNER_RULES))
            validate_product_form_contract(obj.form_schema, obj.signer_rules)
            obj.placement_config = initial_template_configuration(
                None, form_schema=obj.form_schema,
            )
            obj.placement_config.update({
                'document_type': obj.document_type,
                'version': obj.version,
            })
        obj.full_clean()
        super().save_model(request, obj, form, change)
        OriginationDocumentProductEligibility.objects.bulk_create([
            OriginationDocumentProductEligibility(
                template=obj, product=product, created_by=request.user,
            )
            for product in form.cleaned_data.get('eligible_products', [])
        ], ignore_conflicts=True)
        OriginationDocumentTemplateEvent.objects.create(
            template=obj, action='created', actor=request.user,
            metadata={
                'sha256': obj.source_sha256,
                'byte_size': obj.source_byte_size,
                'page_count': obj.page_count,
                'reusable_family': obj.document_type if obj.product_definition_id is None else '',
                'schema_preset': schema_preset,
                'eligible_product_ids': sorted(
                    str(product.pk) for product in form.cleaned_data.get('eligible_products', [])
                ),
            },
        )
        from origination.services.origination_templates import upload_template_record
        upload_template_record(obj, pdf_data=form._pdf_data, actor=request.user)
        if obj.status == OriginationDocumentTemplate.STATUS_UPLOAD_FAILED:
            messages.error(request, obj.upload_error)
        else:
            messages.success(
                request,
                'Template uploaded. Review its fields and align them in the visual builder before activation.',
            )

    def response_add(self, request, obj, post_url_continue=None):
        if obj.drive_file_id and obj.status != OriginationDocumentTemplate.STATUS_UPLOAD_FAILED:
            return HttpResponseRedirect(reverse('admin:origination_originationdocumenttemplate_calibrate', args=[obj.pk]))
        return super().response_add(request, obj, post_url_continue)

    @admin.action(description='Create / open editable version')
    def create_editable_selected_template(self, request, queryset):
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied
        if queryset.count() != 1:
            self.message_user(request, 'Select exactly one document.', level=messages.ERROR)
            return None
        selected = queryset.first()
        if selected.status == selected.STATUS_READY:
            return HttpResponseRedirect(reverse(
                'admin:origination_originationdocumenttemplate_calibrate', args=[selected.pk],
            ))
        return self.create_editable_version_view(request, str(selected.pk))

    @admin.action(description='Activate selected template')
    def activate_selected_templates(self, request, queryset):
        if not request.user.is_superuser:
            raise PermissionDenied
        if queryset.count() != 1:
            self.message_user(request, 'Select exactly one template to activate.', level=messages.ERROR)
            return
        selected = queryset.first()
        if selected.product_definition_id:
            self.message_user(
                request,
                'Open Calibrate fields and use Publish product; it validates and activates the product in one action.',
                level=messages.ERROR,
            )
            return
        from origination.services.origination_templates import OriginationTemplateError, activate_template
        try:
            template = activate_template(selected, actor=request.user)
        except OriginationTemplateError as exc:
            self.message_user(request, str(exc), level=messages.ERROR)
            return
        self.message_user(request, f'{template} is now active.', level=messages.SUCCESS)


@admin.register(LoanOriginationApplication)
class LoanOriginationApplicationAdmin(OriginationGodModeAdminMixin, ModelAdmin):
    list_display = ('display_reference', 'product_definition', 'officer', 'branch', 'status', 'revision', 'updated_at')
    list_filter = ('status', 'branch', 'product_definition')
    search_fields = ('display_reference', 'reference_number', 'officer__username')
    readonly_fields = ('signing_setup_link',) + tuple(field.name for field in LoanOriginationApplication._meta.fields)
    fieldsets = (
        ('Application', {'fields': ('display_reference', 'product_definition', 'officer', 'branch', 'status', 'signing_setup_link')}),
        ('Advanced', {'classes': ('collapse',), 'fields': tuple(field.name for field in LoanOriginationApplication._meta.fields
            if field.name not in {'display_reference', 'product_definition', 'officer', 'branch', 'status'})}),
    )

    @admin.display(description='Signers')
    def signing_setup_link(self, obj):
        if obj.signing_policy_snapshot != 'all_required':
            return 'Original approval policy'
        return format_html('<a href="{}">Configure signers</a>', reverse(
            'admin:origination_application_signers', args=[obj.pk]))

    def get_urls(self):
        return [path('<uuid:object_id>/signers/', self.admin_site.admin_view(self.signers_view),
            name='origination_application_signers')] + super().get_urls()

    def signers_view(self, request, object_id):
        from origination.admin_signing import application_signers_view
        return application_signers_view(self, request, object_id)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class OriginationCommercialExceptionForm(forms.ModelForm):
    class Meta:
        model = OriginationCommercialException
        fields = ('application', 'reason', 'approval_reference')
        widgets = {'reason': forms.Textarea(attrs={'rows': 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['application'].queryset = LoanOriginationApplication.objects.filter(
            status__in=[
                LoanOriginationApplication.STATUS_DRAFT,
                LoanOriginationApplication.STATUS_CORRECTION_REQUIRED,
            ],
        ).select_related('product_version', 'product_definition').order_by('-updated_at')
        self.fields['application'].help_text = (
            'Choose the exact editable application revision. Any later edit invalidates this approval.'
        )

    def clean(self):
        cleaned = super().clean()
        application = cleaned.get('application')
        if not application:
            return cleaned
        from origination.services.origination_commercial_terms import validate_commercial_terms
        validation = validate_commercial_terms(application)
        if not validation['enabled']:
            self.add_error('application', 'This application does not use the governed Commercial Terms contract.')
            return cleaned
        if any(not item['waivable'] for item in validation['blocking_findings']):
            self.add_error(
                'application',
                'Fix missing, invalid, or internally inconsistent values before approving a policy exception.',
            )
        elif not validation['policy_mismatch_codes']:
            self.add_error('application', 'This revision has no product-policy mismatch to approve.')
        elif OriginationCommercialException.objects.filter(
            application=application,
            application_revision=application.revision,
            entered_terms_sha256=validation['entered_terms_sha256'],
            expected_quote_sha256=validation['expected_quote_sha256'],
        ).exists():
            self.add_error('application', 'This exact revision already has a commercial exception.')
        self._commercial_validation = validation
        return cleaned


@admin.register(OriginationCommercialException)
class OriginationCommercialExceptionAdmin(OriginationGodModeAdminMixin, ModelAdmin):
    form = OriginationCommercialExceptionForm
    list_display = (
        'application', 'application_revision', 'product_version',
        'approval_reference', 'approved_by', 'approved_at',
    )
    list_filter = ('approved_at', 'product_version__product')
    search_fields = (
        'application__reference_number', 'approval_reference',
        'approved_by__username',
    )
    readonly_fields = (
        'application_revision', 'product_version', 'entered_terms_sha256',
        'expected_quote_sha256', 'covered_mismatch_codes', 'approved_by', 'approved_at',
    )

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields if obj else ()

    def get_fields(self, request, obj=None):
        if obj:
            return (
                'application', 'application_revision', 'product_version',
                'covered_mismatch_codes', 'reason', 'approval_reference',
                'entered_terms_sha256', 'expected_quote_sha256',
                'approved_by', 'approved_at',
            )
        return ('application', 'reason', 'approval_reference')

    def save_model(self, request, obj, form, change):
        if change or not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied
        validation = getattr(form, '_commercial_validation', None)
        if not validation:
            raise ValidationError('Commercial validation must complete before approval.')
        obj.application_revision = obj.application.revision
        obj.product_version = obj.application.product_version
        obj.entered_terms_sha256 = validation['entered_terms_sha256']
        obj.expected_quote_sha256 = validation['expected_quote_sha256']
        obj.covered_mismatch_codes = sorted(set(validation['policy_mismatch_codes']))
        obj.approved_by = request.user
        super().save_model(request, obj, form, change)
        OriginationApplicationEvent.objects.create(
            application=obj.application, action='commercial_exception_approved',
            revision=obj.application_revision, actor=request.user,
            after_values={
                'exception_id': str(obj.pk),
                'covered_mismatch_codes': obj.covered_mismatch_codes,
                'approval_reference': obj.approval_reference,
            },
            metadata={
                'entered_terms_sha256': obj.entered_terms_sha256,
                'expected_quote_sha256': obj.expected_quote_sha256,
            },
        )

    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return bool(obj is None and self.has_add_permission(request))

    def has_delete_permission(self, request, obj=None):
        return False


class _AppendOnlyOriginationAdmin(OriginationGodModeAdminMixin, ModelAdmin):
    def get_readonly_fields(self, request, obj=None):
        excluded = set(self.exclude or ())
        return tuple(field.name for field in self.model._meta.fields if field.name not in excluded)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return True

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(OriginationDataFieldEvent)
class OriginationDataFieldEventAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('data_field', 'action', 'actor', 'occurred_at')
    list_filter = ('action',)
    search_fields = ('data_field__key', 'data_field__label')

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(OriginationDocumentTemplateEvent)
class OriginationDocumentTemplateEventAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('template', 'action', 'actor', 'occurred_at')
    list_filter = ('action',)
    search_fields = ('template__name', 'template__document_type')


@admin.register(OriginationProductDefinitionEvent)
class OriginationProductDefinitionEventAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('product_definition', 'action', 'actor', 'occurred_at')
    list_filter = ('action',)
    search_fields = ('product_definition__product_key', 'product_definition__name')


@admin.register(OriginationTemplateConfigurationRevision)
class OriginationTemplateConfigurationRevisionAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('template', 'revision', 'is_published', 'created_by', 'created_at', 'published_at')
    list_filter = ('is_published', 'template__document_type')
    search_fields = ('template__name', 'template__document_type')


@admin.register(OriginationApplicationEvent)
class OriginationApplicationEventAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('application', 'action', 'revision', 'actor', 'occurred_at')
    list_filter = ('action',)
    search_fields = ('application__reference_number', 'request_id')


@admin.register(OriginationApplicationDocument)
class OriginationApplicationDocumentAdmin(_AppendOnlyOriginationAdmin):
    list_display = (
        'application', 'document_key', 'document_role', 'selected',
        'applicable', 'previewed_application_revision', 'updated_at',
    )
    list_filter = ('document_role', 'inclusion_mode', 'selected', 'applicable')
    search_fields = ('application__reference_number', 'document_key', 'name')


@admin.register(OriginationCorrectionRequest)
class OriginationCorrectionRequestAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('application', 'application_revision', 'reviewer', 'status', 'created_at', 'addressed_at')
    list_filter = ('status', 'created_at')
    search_fields = ('application__reference_number', 'summary', 'reviewer__username')


@admin.register(OriginationCorrectionItem)
class OriginationCorrectionItemAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('correction_request', 'target_type', 'target_label', 'created_at')
    list_filter = ('target_type',)
    search_fields = ('correction_request__application__reference_number', 'target_key', 'target_label')


@admin.register(OriginationRequirementEvidence)
class OriginationRequirementEvidenceAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('application', 'requirement_label', 'original_filename', 'status', 'uploaded_by', 'created_at')
    list_filter = ('status', 'mime_type', 'requirement_key')
    search_fields = ('application__reference_number', 'requirement_label', 'original_filename', 'content_sha256')


@admin.register(OriginationSigningPackage)
class OriginationSigningPackageAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('external_reference', 'application', 'application_revision', 'status', 'archive_status', 'updated_at')
    list_filter = ('status', 'archive_status', 'document_type')
    search_fields = ('external_reference', 'application__reference_number')
    exclude = ('frozen_unsigned_document', 'pending_signed_document')


@admin.register(OriginationSigningParticipant)
class OriginationSigningParticipantAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('application', 'participant_key', 'role', 'staff_user', 'created_at')
    search_fields = ('application__reference_number', 'participant_key')


@admin.register(OriginationConsentPolicyVersion)
class OriginationConsentPolicyVersionAdmin(OriginationGodModeAdminMixin, ModelAdmin):
    list_display = (
        'version', 'status', 'approval_reference', 'approved_by', 'approved_at',
        'retired_by', 'retired_at', 'created_at',
    )
    list_filter = ('status', 'approved_at')
    search_fields = ('version', 'approval_reference', 'content_sha256')
    readonly_fields = (
        'status', 'content_sha256', 'created_by', 'approved_by', 'approved_at',
        'retired_by', 'retired_at', 'created_at',
    )
    actions = ('activate_selected_policy', 'retire_selected_policy')

    def has_module_permission(self, request):
        return request.user.is_superuser

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return False if obj else request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.created_by = request.user
        obj.status = obj.STATUS_DRAFT
        obj.full_clean()
        return super().save_model(request, obj, form, change)

    @admin.action(description='Activate selected compliance-approved consent policy')
    def activate_selected_policy(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, 'Select exactly one consent policy.', level=messages.ERROR)
            return
        policy_id = queryset.values_list('pk', flat=True).first()
        with transaction.atomic():
            policy = OriginationConsentPolicyVersion.objects.select_for_update().get(pk=policy_id)
            if policy.status != policy.STATUS_DRAFT:
                self.message_user(request, 'Only a draft consent policy can be activated.', level=messages.ERROR)
                return
            now = timezone.now()
            policy.status = policy.STATUS_ACTIVE
            policy.approved_by = request.user
            policy.approved_at = now
            OriginationConsentPolicyVersion.objects.select_for_update().filter(
                status=policy.STATUS_ACTIVE,
                approval_roles=policy.approval_roles,
                signing_policy=policy.signing_policy,
            ).exclude(pk=policy.pk).update(
                status=policy.STATUS_RETIRED, retired_by=request.user, retired_at=now,
            )
            policy.full_clean()
            OriginationConsentPolicyVersion.objects.filter(pk=policy.pk).update(
                status=policy.STATUS_ACTIVE, approved_by=request.user, approved_at=now,
            )
        self.message_user(
            request,
            f'Consent policy {policy.version} activated with approval reference {policy.approval_reference}.',
            level=messages.SUCCESS,
        )

    @admin.action(description='Retire selected active consent policy')
    def retire_selected_policy(self, request, queryset):
        if queryset.count() != 1:
            self.message_user(request, 'Select exactly one consent policy.', level=messages.ERROR)
            return
        policy_id = queryset.values_list('pk', flat=True).first()
        with transaction.atomic():
            policy = OriginationConsentPolicyVersion.objects.select_for_update().get(pk=policy_id)
            if policy.status != policy.STATUS_ACTIVE:
                self.message_user(request, 'Only the active consent policy can be retired.', level=messages.ERROR)
                return
            now = timezone.now()
            OriginationConsentPolicyVersion.objects.filter(pk=policy.pk).update(
                status=policy.STATUS_RETIRED, retired_by=request.user, retired_at=now,
            )
        self.message_user(request, f'Consent policy {policy.version} retired.', level=messages.SUCCESS)


@admin.register(OriginationSigningActionInvalidation)
class OriginationSigningActionInvalidationAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('action', 'invalidated_by', 'reason', 'created_at')
    search_fields = ('action__package__external_reference', 'reason', 'request_id')


@admin.register(OriginationSignerSession)
class OriginationSignerSessionAdmin(_AppendOnlyOriginationAdmin):
    list_display = (
        'package', 'signer_role', 'status', 'sms_provider', 'access_mode', 'masked_phone',
        'shared_phone_approved_by', 'verified_at', 'created_at',
    )
    list_filter = ('status', 'sms_provider', 'access_mode', 'signer_role', 'is_active')
    search_fields = ('package__external_reference', 'package__application__reference_number', 'phone_last4')
    exclude = ('token_hash', 'phone_normalized', 'phone_hash', 'signature_capture')

    @admin.display(description='Phone')
    def masked_phone(self, obj):
        return f'+254•••••{obj.phone_last4}' if obj.phone_last4 else '—'


@admin.register(OriginationOtpChallenge)
class OriginationOtpChallengeAdmin(_AppendOnlyOriginationAdmin):
    list_display = (
        'session', 'send_sequence', 'delivery_status', 'attempts_remaining',
        'expires_at', 'verified_at', 'created_at',
    )
    list_filter = ('delivery_status', 'verified_at', 'created_at')
    search_fields = ('session__package__external_reference', 'provider_message_id')
    exclude = ('code_hash', 'source_ip_hash', 'binding_sha256')


@admin.register(OriginationSigningRequestEvent)
class OriginationSigningRequestEventAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('session', 'action', 'request_id', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('session__package__external_reference',)
    exclude = ('token_hash', 'source_ip_hash', 'payload_digest')


class OriginationStampAssetAdminForm(forms.ModelForm):
    image_upload = forms.FileField(
        label='Transparent PNG stamp', required=False,
        help_text='PNG only, at most 2 MB. Create a new version to replace an active stamp.',
    )

    class Meta:
        model = OriginationStampAsset
        fields = ('name', 'branch', 'environment', 'active')

    def clean_image_upload(self):
        upload = self.cleaned_data.get('image_upload')
        if not upload:
            if not self.instance.pk:
                raise ValidationError('Choose the approved PNG stamp image.')
            return None
        if self.instance.pk:
            raise ValidationError('Stamp image bytes are immutable. Add a new stamp version instead.')
        if int(getattr(upload, 'size', 0) or 0) > 2 * 1024 * 1024:
            raise ValidationError('The stamp PNG must not exceed 2 MB.')
        data = upload.read()
        upload.seek(0)
        try:
            from io import BytesIO
            from PIL import Image
            image = Image.open(BytesIO(data))
            image.verify()
            if image.format != 'PNG':
                raise ValueError('not png')
            if image.width > 2000 or image.height > 2000:
                raise ValidationError('The stamp image must be no larger than 2000 × 2000 pixels.')
        except ValidationError:
            raise
        except Exception as exc:
            raise ValidationError('Choose a genuine, readable PNG stamp image.') from exc
        upload._validated_stamp_bytes = data
        return upload


@admin.register(OriginationStampAsset)
class OriginationStampAssetAdmin(OriginationGodModeAdminMixin, ModelAdmin):
    form = OriginationStampAssetAdminForm
    list_display = ('name', 'branch', 'environment', 'version', 'active', 'activated_at')
    list_filter = ('environment', 'active', 'branch')
    search_fields = ('name', 'content_sha256', 'branch__name')
    readonly_fields = (
        'version', 'content_sha256', 'byte_size', 'created_by',
        'activated_by', 'activated_at', 'created_at',
    )

    def has_add_permission(self, request):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)

    def save_model(self, request, obj, form, change):
        upload = form.cleaned_data.get('image_upload')
        if not change:
            import hashlib
            data = bytes(upload._validated_stamp_bytes)
            obj.image_png = data
            obj.content_sha256 = hashlib.sha256(data).hexdigest()
            obj.byte_size = len(data)
            obj.created_by = request.user
            obj.version = (
                OriginationStampAsset.objects.filter(
                    name__iexact=obj.name, branch=obj.branch,
                    environment=obj.environment,
                ).aggregate(models.Max('version'))['version__max'] or 0
            ) + 1
        if obj.active:
            OriginationStampAsset.objects.filter(
                name__iexact=obj.name, branch=obj.branch,
                environment=obj.environment, active=True,
            ).exclude(pk=obj.pk).update(active=False)
            obj.activated_by = request.user
            obj.activated_at = timezone.now()
        super().save_model(request, obj, form, change)
        self.message_user(
            request,
            f'{obj} saved. Test stamps remain unusable for production signing.',
            level=messages.SUCCESS,
        )


@admin.register(OriginationSigningAction)
class OriginationSigningActionAdmin(_AppendOnlyOriginationAdmin):
    list_display = (
        'package', 'document_key', 'slot_key', 'signer_role',
        'action_type', 'mode', 'actor', 'signer_session', 'created_at',
    )
    list_filter = ('mode', 'action_type', 'signer_role')
    search_fields = ('package__external_reference', 'document_key', 'slot_key', 'request_id')
    exclude = ('metadata',)


@admin.register(OriginationReportingValue)
class OriginationReportingValueAdmin(_AppendOnlyOriginationAdmin):
    list_display = ('application', 'field_key', 'value_type', 'sensitivity', 'projected_at')
    list_filter = ('value_type', 'sensitivity', 'reporting_use', 'export_allowed')
    search_fields = ('application__reference_number', 'field_key', 'data_field__key')


from core.admin_utils import auto_register_unregistered_models
AUTO_REGISTERED_MODELS = auto_register_unregistered_models(app_label='origination')
