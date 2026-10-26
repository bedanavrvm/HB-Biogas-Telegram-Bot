"""Forms used by the guided Origination product setup workspace."""

from __future__ import annotations

import json

from django import forms
from django.forms import inlineformset_factory
from django.utils.text import slugify

from origination.models import OriginationDocumentTemplate, OriginationProductDefinition
from core.models import (
    OperationalLocation,
    Product,
    ProductCustomAttribute,
    ProductFee,
    ProductRequirement,
    ProductVersion,
)


class SetupIdentityForm(forms.ModelForm):
    branches = forms.ModelMultipleChoiceField(
        queryset=OperationalLocation.objects.none(),
        widget=forms.CheckboxSelectMultiple,
        help_text='Choose every branch where officers may start this product.',
    )

    class Meta:
        model = Product
        fields = ('name', 'code', 'category', 'description', 'sort_order')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['code'].required = False
        self.fields['code'].widget = forms.HiddenInput()
        self.fields['sort_order'].required = False
        if self.is_bound and self.data.get('intent') == 'stay':
            self.fields['branches'].required = False
        self.fields['branches'].queryset = OperationalLocation.objects.filter(
            location_type='branch', active=True,
        ).order_by('sort_order', 'name')
        if self.instance.pk and not self.is_bound:
            self.initial['branches'] = self.instance.availability_assignments.filter(
                workflow='loan_origination', active=True,
            ).values_list('branch_id', flat=True)
            self.fields['code'].disabled = True

    def clean_code(self):
        if self.instance.pk:
            return self.instance.code
        supplied = self.cleaned_data.get('code')
        if supplied:
            return supplied
        base = slugify(self.cleaned_data.get('name') or 'loan').replace('-', '_')[:65] or 'loan'
        candidate, number = base, 2
        while Product.objects.filter(code=candidate).exists():
            candidate = f'{base}_{number}'
            number += 1
        return candidate

    def clean_sort_order(self):
        return self.cleaned_data.get('sort_order') or 0


class SetupTermsForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for key in ('quote_amount_field_key', 'quote_tenor_field_key'):
            self.fields[key].disabled = True
            self.fields[key].widget = forms.HiddenInput()
        if self.is_bound and self.data.get('intent') == 'stay':
            data = self.data.copy()
            for key, field in self.fields.items():
                if field.required and not str(data.get(key) or '').strip():
                    data[key] = self.initial.get(key, getattr(self.instance, key, ''))
            self.data = data

    class Meta:
        model = ProductVersion
        fields = (
            'currency', 'min_amount', 'max_amount', 'min_tenor', 'max_tenor',
            'tenor_unit', 'interest_method', 'interest_rate',
            'interest_rate_period', 'repayment_frequency',
            'quote_amount_field_key', 'quote_tenor_field_key',
            'effective_from', 'effective_to',
        )
        widgets = {
            'effective_from': forms.DateInput(attrs={'type': 'date'}),
            'effective_to': forms.DateInput(attrs={'type': 'date'}),
        }


class OptionalSetupRowMixin:
    """Ignore a displayed empty row whose model defaults were posted by the browser."""

    def has_changed(self):
        if self.is_bound and not self.instance.pk:
            key = str(self.data.get(self.add_prefix('key')) or '').strip()
            label = str(self.data.get(self.add_prefix('label')) or '').strip()
            if not key and not label:
                return False
        return super().has_changed()


class SetupFeeForm(OptionalSetupRowMixin, forms.ModelForm):
    class Meta:
        model = ProductFee
        fields = (
            'position', 'key', 'label', 'fee_type', 'fixed_amount', 'percentage',
            'calculation_basis', 'minimum_amount', 'maximum_amount',
            'collection_mode', 'mandatory',
        )


class SetupRequirementForm(OptionalSetupRowMixin, forms.ModelForm):
    minimum = forms.DecimalField(required=False)
    maximum = forms.DecimalField(required=False)
    enforcement_stage = forms.ChoiceField(required=False, choices=(
        ('', 'No transition requirement'), ('review', 'Before review'), ('signing', 'Before signing'),
    ))

    class Meta:
        model = ProductRequirement
        fields = (
            'position', 'key', 'label', 'description', 'requirement_type',
            'enforcement_stage', 'required', 'active', 'minimum', 'maximum',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        config = self.instance.validation_config if self.instance.pk else {}
        self.fields['minimum'].initial = self.initial.get('minimum', config.get('min'))
        self.fields['maximum'].initial = self.initial.get('maximum', config.get('max'))
        stage = self.initial.get('enforcement_stage', '')
        if stage and stage not in {'review', 'signing'}:
            self.fields['enforcement_stage'].choices.append((stage, stage + ' (retained legacy stage)'))

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.workflow = 'loan_origination'
        instance.validation_config = {
            key: str(value) for key, value in {
                'min': self.cleaned_data.get('minimum'),
                'max': self.cleaned_data.get('maximum'),
            }.items() if value is not None
        }
        if commit:
            instance.save()
        return instance


class SetupAttributeForm(OptionalSetupRowMixin, forms.ModelForm):
    choices = forms.CharField(
        required=False, widget=forms.Textarea(attrs={'rows': 3}),
        help_text='For Choice fields, enter one option per line.',
    )

    class Meta:
        model = ProductCustomAttribute
        fields = (
            'position', 'key', 'label', 'attribute_type', 'required',
            'help_text', 'choices',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['choices'].initial = self.initial.get('choices', '\n'.join(str(item) for item in (self.instance.options or [])))

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.options = [
            item.strip() for item in self.cleaned_data.get('choices', '').splitlines()
            if item.strip()
        ]
        instance.workflow_visibility = ['loan_origination']
        if commit:
            instance.save()
        return instance

    def clean(self):
        cleaned = super().clean()
        self.instance.options = [item.strip() for item in cleaned.get('choices', '').splitlines() if item.strip()]
        return cleaned


class LocalConfigurationFormSet(forms.BaseFormSet):
    def clean(self):
        super().clean()
        keys = [form.cleaned_data.get('key') for form in self.forms
                if form.cleaned_data and not form.cleaned_data.get('DELETE')]
        if len(keys) != len(set(keys)):
            raise forms.ValidationError('Use a distinct key for each item.')


def local_configuration_forms(data, configuration):
    configuration = configuration or {}
    requirements = [{**item, 'requirement_type': item['type'], 'active': item.get('active', True),
        'position': index, 'minimum': (item.get('validation') or {}).get('min'),
        'maximum': (item.get('validation') or {}).get('max')}
        for index, item in enumerate(configuration.get('requirements', []))]
    attributes = [{**item, 'attribute_type': item['type'], 'position': index,
        'choices': '\n'.join(str(option) for option in item.get('options', []))}
        for index, item in enumerate(configuration.get('custom_attributes', []))]
    factory = forms.formset_factory
    return (factory(SetupRequirementForm, formset=LocalConfigurationFormSet, extra=1, can_delete=True)(
                data, initial=requirements, prefix='requirements'),
            factory(SetupAttributeForm, formset=LocalConfigurationFormSet, extra=1, can_delete=True)(
                data, initial=attributes, prefix='attributes'))


def local_configuration_values(requirements, attributes, previous):
    result = {'version': 1, 'requirements': [], 'custom_attributes': []}
    for name, formset in [('requirements', requirements), ('custom_attributes', attributes)]:
        originals = {item['key']: item for item in (previous or {}).get(name, [])}
        for form in formset.forms:
            if not form.cleaned_data or form.cleaned_data.get('DELETE') or not form.cleaned_data.get('key'):
                continue
            instance = form.save(commit=False)
            item = {**originals.get(instance.key, {}), 'key': instance.key, 'label': instance.label,
                    'required': instance.required}
            if name == 'requirements':
                item.update(type=instance.requirement_type, description=instance.description,
                    validation=instance.validation_config, workflow='loan_origination',
                    enforcement_stage=instance.enforcement_stage, active=instance.active)
            else:
                item.update(type=instance.attribute_type, help_text=instance.help_text,
                    options=instance.options, workflows=['loan_origination'])
            result[name].append(item)
    return result


FeeFormSet = inlineformset_factory(
    ProductVersion, ProductFee, form=SetupFeeForm, extra=1, can_delete=True,
)


class SetupFormContractForm(forms.ModelForm):
    class Meta:
        model = OriginationProductDefinition
        fields = ('form_schema', 'signer_rules')
        widgets = {
            'form_schema': forms.HiddenInput,
            'signer_rules': forms.HiddenInput,
        }

    def clean_form_schema(self):
        value = self.cleaned_data['form_schema']
        return json.loads(value) if isinstance(value, str) else value

    def clean_signer_rules(self):
        value = self.cleaned_data['signer_rules']
        return json.loads(value) if isinstance(value, str) else value


class SetupDocumentForm(forms.Form):
    SOURCE_EXISTING = 'existing'
    SOURCE_UPLOAD = 'upload'
    source = forms.ChoiceField(choices=(
        (SOURCE_EXISTING, 'Use a published reusable LAF'),
        (SOURCE_UPLOAD, 'Upload a new product LAF'),
    ), widget=forms.RadioSelect)
    reusable_template = forms.ModelChoiceField(
        queryset=OriginationDocumentTemplate.objects.none(), required=False,
        empty_label='Choose a published LAF',
    )
    pdf_file = forms.FileField(
        required=False, widget=forms.FileInput(attrs={'accept': 'application/pdf'}),
    )

    def __init__(self, *args, reusable_queryset, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['reusable_template'].queryset = reusable_queryset

    def clean(self):
        cleaned = super().clean()
        if cleaned.get('source') == self.SOURCE_EXISTING and not cleaned.get('reusable_template'):
            self.add_error('reusable_template', 'Choose a published reusable LAF.')
        if cleaned.get('source') == self.SOURCE_UPLOAD and not cleaned.get('pdf_file'):
            self.add_error('pdf_file', 'Choose the blank LAF PDF.')
        return cleaned


class SetupCatalogueSelectionForm(forms.Form):
    approval_mode = forms.ChoiceField(required=False, label='Final approval', choices=(
        ('', 'Keep current approval policy'),
        ('all_required', 'All required signers complete approval'),
        ('independent', 'Independent review after signing'),
        ('bm', 'Branch Manager approves and signs'),
        ('management', 'Branch Manager, then Management'),
    ))
    templates = forms.ModelMultipleChoiceField(
        queryset=OriginationDocumentTemplate.objects.none(), required=False,
        label='Available documents', widget=forms.CheckboxSelectMultiple,
    )
    default_signers = forms.MultipleChoiceField(required=False, label='Default signers',
        widget=forms.CheckboxSelectMultiple,
        help_text='Document-required signers stay required. Individual application changes are made in Admin.')

    def __init__(self, *args, definition, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['default_signers'].choices = [
            (str(item.get('participant_key') or item['role']), str(item.get('label') or item['role']).replace('_', ' ').title())
            for item in definition.signer_rules if isinstance(item, dict) and item.get('role')]
        self.initial['default_signers'] = [str(item.get('participant_key') or item.get('role'))
            for item in definition.signing_defaults] or [str(item.get('participant_key') or item['role']) for item in definition.signer_rules
                if item.get('required', True) or any(slot.get('required') for slot in item.get('slots', []))]
        if not definition.supersedes_id and definition.lifecycle_status == 'draft':
            self.initial['approval_mode'] = 'all_required'
        from django.db.models import Q
        self.fields['templates'].queryset = OriginationDocumentTemplate.objects.filter(
            Q(status='active', published_configuration_revision__is_published=True)
            | Q(status='ready', product_eligibilities__product_id=definition.product_version.product_id),
        ).distinct().order_by('document_role', 'name', '-version')
        self.fields['templates'].label_from_instance = lambda item: (
            f'{item.name} · v{item.version} · {item.get_document_role_display()} · {item.get_status_display()}'
        )
        if definition.lifecycle_status != definition.STATUS_DRAFT:
            self.fields.pop('approval_mode')
            self.fields.pop('default_signers')
        if not self.is_bound:
            from origination.services.origination_setup_documents import selected_documents
            self.initial['templates'] = selected_documents(definition)


class SetupCatalogueUploadForm(forms.Form):
    name = forms.CharField(max_length=180, label='Document name')
    role = forms.ChoiceField(choices=OriginationDocumentTemplate.ROLE_CHOICES, label='Purpose')
    preset = forms.ChoiceField(required=False, label='Starting fields', choices=(
        ('', 'Set up fields visually'),
        ('generic_jawabu_laf', 'Reviewed Jawabu LAF fields'),
    ))
    pdf_file = forms.FileField(label='Blank PDF', widget=forms.FileInput(attrs={'accept': 'application/pdf'}))
