"""Forms used by the guided Origination product setup workspace."""

from __future__ import annotations

import json

from django import forms
from django.forms import inlineformset_factory

from core.models import (
    OperationalLocation,
    OriginationDocumentTemplate,
    OriginationProductDefinition,
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
        self.fields['branches'].queryset = OperationalLocation.objects.filter(
            location_type='branch', active=True,
        ).order_by('sort_order', 'name')
        if self.instance.pk and not self.is_bound:
            self.initial['branches'] = self.instance.availability_assignments.filter(
                workflow='loan_origination', active=True,
            ).values_list('branch_id', flat=True)
            self.fields['code'].disabled = True


class SetupTermsForm(forms.ModelForm):
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

    class Meta:
        model = ProductRequirement
        fields = (
            'position', 'key', 'label', 'description', 'requirement_type',
            'enforcement_stage', 'required', 'active', 'minimum', 'maximum',
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        config = self.instance.validation_config if self.instance.pk else {}
        self.fields['minimum'].initial = config.get('min')
        self.fields['maximum'].initial = config.get('max')

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
        self.fields['choices'].initial = '\n'.join(str(item) for item in (self.instance.options or []))

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


FeeFormSet = inlineformset_factory(
    ProductVersion, ProductFee, form=SetupFeeForm, extra=1, can_delete=True,
)
RequirementFormSet = inlineformset_factory(
    ProductVersion, ProductRequirement, form=SetupRequirementForm, extra=1, can_delete=True,
)
AttributeFormSet = inlineformset_factory(
    ProductVersion, ProductCustomAttribute, form=SetupAttributeForm, extra=1, can_delete=True,
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
