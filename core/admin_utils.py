from __future__ import annotations

from django.apps import apps
from django.contrib import admin
from django.contrib.admin.sites import AlreadyRegistered
from django.db import models
from unfold.admin import ModelAdmin


HEAVY_LIST_DISPLAY_FIELDS = (
    models.BinaryField,
    models.FileField,
    models.ImageField,
    models.JSONField,
    models.TextField,
)

NOISE_FIELD_NAMES = {
    'id',
    'uuid',
    'password',
    'session_data',
    'signed_document_hash',
    'webhook_delivery_id',
    'external_reference',
}
NOISE_FIELD_SUFFIXES = ('_hash', '_token', '_payload')
DEFAULT_MAX_LIST_COLUMNS = 6

AUTO_ADMIN_OVERRIDES = {
    'admin.LogEntry': {
        'list_display': ('action_time', 'user', 'content_type', 'action_flag', 'object_repr'),
        'list_filter': ('action_flag', 'content_type', 'action_time'),
        'search_fields': ('object_repr', 'change_message', 'user__username'),
        'date_hierarchy': 'action_time',
    },
    'auth.Permission': {
        'list_display': ('name', 'content_type', 'codename'),
        'list_filter': ('content_type__app_label',),
        'search_fields': ('name', 'codename', 'content_type__app_label', 'content_type__model'),
    },
    'contenttypes.ContentType': {
        'list_display': ('app_label', 'model'),
        'list_filter': ('app_label',),
        'search_fields': ('app_label', 'model'),
    },
    'sessions.Session': {
        'list_display': ('expire_date',),
        'list_filter': ('expire_date',),
        'date_hierarchy': 'expire_date',
    },
    'core.ComplaintCaseSequence': {
        'list_display': ('group_id', 'year', 'next_number', 'updated_at'),
        'list_filter': ('year', 'updated_at'),
        'search_fields': ('group_id',),
    },
    'core.SpinRequestSequence': {
        'list_display': ('group_id', 'year', 'next_number', 'updated_at'),
        'list_filter': ('year', 'updated_at'),
        'search_fields': ('group_id',),
    },
    'core.ComplaintCaseStaffMember': {
        'list_display': ('name', 'role', 'active', 'group_configuration', 'telegram_username', 'updated_at'),
        'list_filter': ('active', 'role', 'group_configuration'),
        'search_fields': ('name', 'telegram_username', 'telegram_user_id', 'group_configuration__display_name'),
    },
    'core.TatTrackerApprovalCertificate': {
        'list_display': ('case', 'staff_member', 'stage_key', 'status', 'signed_at', 'updated_at'),
        'list_filter': ('status', 'stage_key', 'created_at'),
        'search_fields': ('case__case_id', 'case__client_name', 'staff_member__name', 'stage_key'),
    },
}


def lightweight_list_display(model: type[models.Model]) -> tuple[str, ...]:
    """Return concrete field names that are useful and cheap in list views."""
    override = AUTO_ADMIN_OVERRIDES.get(model._meta.label)
    if override and override.get('list_display'):
        return override['list_display']

    field_names: list[str] = []
    preferred: list[str] = []
    fallback: list[str] = []
    for field in model._meta.fields:
        if should_hide_from_list_display(field):
            continue
        target = preferred if is_preferred_list_field(field) else fallback
        target.append(field.name)
    field_names = (preferred + fallback)[:DEFAULT_MAX_LIST_COLUMNS]
    return tuple(field_names) or ('__str__',)


def should_hide_from_list_display(field: models.Field) -> bool:
    name = field.name
    if isinstance(field, HEAVY_LIST_DISPLAY_FIELDS):
        return True
    if name in NOISE_FIELD_NAMES:
        return True
    if getattr(field, 'primary_key', False):
        return True
    return any(name.endswith(suffix) for suffix in NOISE_FIELD_SUFFIXES)


def is_preferred_list_field(field: models.Field) -> bool:
    name = field.name
    if isinstance(field, (models.DateTimeField, models.DateField)):
        return name not in {'created_at', 'updated_at'}
    return (
        'name' in name
        or name in {'status', 'state', 'role', 'active', 'year', 'next_number'}
        or name.endswith('_type')
        or name.endswith('_configuration')
    )


def lightweight_list_filter(model: type[models.Model], list_display: tuple[str, ...]) -> tuple[str, ...]:
    override = AUTO_ADMIN_OVERRIDES.get(model._meta.label)
    if override and override.get('list_filter'):
        return override['list_filter']

    filters: list[str] = []
    for field in model._meta.fields:
        if field.name not in list_display:
            continue
        if isinstance(field, (models.BooleanField, models.DateField, models.DateTimeField, models.ForeignKey)):
            filters.append(field.name)
        elif getattr(field, 'choices', None):
            filters.append(field.name)
    return tuple(filters[:4])


def lightweight_search_fields(model: type[models.Model], list_display: tuple[str, ...]) -> tuple[str, ...]:
    override = AUTO_ADMIN_OVERRIDES.get(model._meta.label)
    if override and override.get('search_fields'):
        return override['search_fields']

    fields: list[str] = []
    for field in model._meta.fields:
        if field.name not in list_display:
            continue
        if isinstance(field, (models.CharField, models.EmailField, models.SlugField)):
            fields.append(field.name)
    return tuple(fields[:5])


def lightweight_date_hierarchy(model: type[models.Model], list_display: tuple[str, ...]) -> str | None:
    override = AUTO_ADMIN_OVERRIDES.get(model._meta.label)
    if override and override.get('date_hierarchy'):
        return override['date_hierarchy']

    for candidate in ('updated_at', 'created_at'):
        if any(field.name == candidate for field in model._meta.fields):
            return candidate
    for field in model._meta.fields:
        if field.name in list_display and isinstance(field, (models.DateField, models.DateTimeField)):
            return field.name
    return None


def auto_register_unregistered_models() -> list[type[models.Model]]:
    """Register models missing from Django admin without replacing custom admins."""
    registered: list[type[models.Model]] = []
    for model in apps.get_models():
        if model in admin.site._registry:
            continue
        list_display = lightweight_list_display(model)
        attrs = {
            '__module__': __name__,
            'list_display': list_display,
        }
        list_filter = lightweight_list_filter(model, list_display)
        if list_filter:
            attrs['list_filter'] = list_filter
        search_fields = lightweight_search_fields(model, list_display)
        if search_fields:
            attrs['search_fields'] = search_fields
        date_hierarchy = lightweight_date_hierarchy(model, list_display)
        if date_hierarchy:
            attrs['date_hierarchy'] = date_hierarchy
        model_admin = type(
            f'{model.__name__}AutoAdmin',
            (ModelAdmin,),
            attrs,
        )
        try:
            admin.site.register(model, model_admin)
        except AlreadyRegistered:
            continue
        registered.append(model)
    return registered
