"""Security lifecycle hooks for canonical staff accounts."""

from django.contrib.auth import get_user_model
from django.db.models.signals import post_save, pre_delete, pre_save
from django.dispatch import receiver


User = get_user_model()


@receiver(pre_delete, sender=User, dispatch_uid='core.require_governed_user_hard_delete')
def require_governed_user_hard_delete(sender, instance, **kwargs):
    from core.services.user_hard_delete import require_governed_user_hard_delete as require_authority

    require_authority()


@receiver(pre_save, sender=User, dispatch_uid='core.capture_user_access_deactivation')
def capture_user_access_deactivation(sender, instance, **kwargs):
    if not instance.pk:
        instance._retire_miniapp_access = False
        return
    previous = sender.objects.filter(pk=instance.pk).values_list('is_active', flat=True).first()
    instance._retire_miniapp_access = bool(previous and not instance.is_active)


@receiver(post_save, sender=User, dispatch_uid='core.retire_user_access_on_deactivation')
def retire_user_access_on_deactivation(sender, instance, **kwargs):
    if not getattr(instance, '_retire_miniapp_access', False):
        return
    from core.services.access_control import retire_user_access

    retire_user_access(
        user=instance,
        actor=getattr(instance, '_access_retirement_actor', None),
        reason='Staff account deactivated; prior Mini App authority requires reapproval.',
    )
