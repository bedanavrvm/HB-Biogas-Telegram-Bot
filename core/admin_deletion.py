"""One explicit, manifest-bound testing action shared by reviewed model admins."""
import logging
import uuid

from django.conf import settings
from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.core import signing
from django.core.exceptions import PermissionDenied
from django.template.response import TemplateResponse
from unfold.admin import ModelAdmin

from core.services.miniapp_deletion import DeletionError, authorize, delete_selection, preview_selection
from core.services.miniapp_deletion_registry import REGISTRY

logger = logging.getLogger(__name__)
SALT = 'miniapp-testing-deletion-v1'


class TestingDeletionMixin:
    def get_actions(self, request):
        actions = super().get_actions(request)
        if (self.model._meta.label in REGISTRY and getattr(settings, 'MINIAPP_TEST_DELETION_ENABLED', False)
                and request.user.is_active and request.user.is_superuser):
            actions.pop('delete_selected', None)
            actions['delete_testing_selection'] = (
                TestingDeletionMixin.delete_testing_selection, 'delete_testing_selection',
                'Delete selected test records…')
        return actions

    @admin.action(description='Delete selected test records…')
    def delete_testing_selection(self, request, queryset):
        authorize(request.user)
        label = self.model._meta.label
        ids = sorted(str(pk) for pk in queryset.values_list('pk', flat=True))
        mode = request.POST.get('deletion_mode', 'keep')
        error = ''
        if request.POST.get('confirm_deletion'):
            try:
                bound = signing.loads(request.POST.get('deletion_token', ''), salt=SALT, max_age=3600)
            except signing.BadSignature as exc:
                raise PermissionDenied('The confirmation expired. Select the records again.') from exc
            if bound['actor'] != request.user.pk or bound['model'] != label or bound['ids'] != ids or bound['mode'] != mode:
                raise PermissionDenied('The confirmation does not match this selection.')
            try:
                result = delete_selection(model_label=label, ids=ids, actor=request.user, mode=mode,
                                          fingerprint=bound['fingerprint'], request_id=bound['request_id'])
            except DeletionError as exc:
                error = str(exc)
            except Exception:
                logger.exception('Testing deletion rolled back: model=%s actor_id=%s', label, request.user.pk)
                error = 'Nothing was deleted. The records could not be safely removed.'
            else:
                self.message_user(request,
                    f"Deleted {result['deleted']} record(s); kept {result['retained']} linked record(s). "
                    f"Sheet cleanup: {len(result['sheet_operations'])} queued update(s). Drive files kept.", messages.SUCCESS)
                return None
        try:
            plan = preview_selection(model_label=label, ids=ids, actor=request.user, mode=mode)
        except DeletionError as exc:
            self.message_user(request, str(exc), messages.ERROR)
            return None
        token = signing.dumps({'actor': request.user.pk, 'model': label, 'ids': ids, 'mode': mode,
                               'fingerprint': plan['fingerprint'], 'request_id': str(uuid.uuid4())}, salt=SALT)
        return TemplateResponse(request, 'admin/core/miniapp_delete_selection.html', {
            **self.admin_site.each_context(request), 'opts': self.model._meta,
            'title': 'Delete selected test records', 'plan': plan, 'error': error,
            'deletion_token': token, 'action_checkbox_name': ACTION_CHECKBOX_NAME,
            'selected_count': len(ids),
        })


class TestingModelAdmin(TestingDeletionMixin, ModelAdmin):
    pass
