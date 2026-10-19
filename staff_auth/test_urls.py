"""Isolated vendor integration harness. Never include this in project URLs."""
from django.http import JsonResponse
from django.urls import include, path
from django.views.decorators.csrf import csrf_protect

from .assurance import require_browser_user


@csrf_protect
def protected_probe(request):
    # No workflow service/grant and no operational data: test identity only.
    return JsonResponse({'user_id': require_browser_user(request).pk})


urlpatterns = [
    path('test-accounts/', include('allauth.urls')),
    path('test-browser/protected/', protected_probe),
]
