from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import ReviewDecision, ReviewRevision, StandardRelease


class HistoryAdmin(ModelAdmin):
    def has_module_permission(self, request):
        return request.user.is_active and request.user.is_superuser

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_view_permission(self, request, obj=None):
        return request.user.is_active and request.user.is_superuser


for model in (ReviewRevision, ReviewDecision, StandardRelease):
    admin.site.register(model, HistoryAdmin)
