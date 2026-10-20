"""Django key hook; safe to import before the application registry is ready."""
from django.core.cache.backends.base import default_key_func
from django.utils.crypto import salted_hmac
from django.views.decorators.debug import sensitive_variables


PRIVACY_KEY_FUNCTION = 'staff_auth.cache_keys.native_cache_key'
SHARED_CACHE_BACKENDS = frozenset({
    'django.core.cache.backends.redis.RedisCache',
    'django.core.cache.backends.memcached.PyMemcacheCache',
    'django.core.cache.backends.memcached.PyLibMCCache',
})


@sensitive_variables()
def native_cache_key(key, key_prefix, version):
    original = default_key_func(key, key_prefix, version)
    if isinstance(key, str) and key.startswith(('allauth:', 'allauth.')):
        return 'staff-auth:v1:' + salted_hmac(
            'staff-browser-native-cache-v1', original, algorithm='sha256',
        ).hexdigest()
    return original
