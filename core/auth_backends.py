from django.conf import settings
from django.contrib.auth.backends import ModelBackend

from core.services.telegram_identity import resolve_user_by_telegram_id, validate_telegram_init_data


class TelegramMiniAppBackend(ModelBackend):
    """Authenticate passwordless staff from verified Telegram Mini App initData."""

    def authenticate(self, request, init_data=None, **kwargs):
        if not init_data:
            return None
        _, identity = validate_telegram_init_data(
            init_data,
            max_age_seconds=int(getattr(settings, 'TELEGRAM_AUTH_MAX_AGE_SECONDS', 86400)),
        )
        return resolve_user_by_telegram_id(identity.telegram_id)
