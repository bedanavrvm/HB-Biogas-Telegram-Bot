from django.contrib import admin

from .models import HomeBiogasAction, HomeBiogasActionEvent

for _model in (HomeBiogasAction, HomeBiogasActionEvent):
    if admin.site.is_registered(_model):
        admin.site.unregister(_model)


@admin.register(HomeBiogasAction)
class HomeBiogasActionAdmin(admin.ModelAdmin):
    list_display = ('farmer', 'source_order_number', 'installation_status', 'commissioning_status', 'updated_at')
    list_filter = ('installation_status', 'commissioning_status', 'readiness_status')
    search_fields = ('source_order_number', 'farmer__customer_name', 'farmer__national_id')
    readonly_fields = ('id', 'revision', 'created_at', 'updated_at')


@admin.register(HomeBiogasActionEvent)
class HomeBiogasActionEventAdmin(admin.ModelAdmin):
    list_display = ('action', 'event_type', 'revision', 'actor_label', 'created_at')
    list_filter = ('event_type',)
    readonly_fields = [field.name for field in HomeBiogasActionEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
