"""biogas_bot URL Configuration"""
from django.contrib import admin
from django.http import HttpResponse
from django.urls import path, include

urlpatterns = [
    path('favicon.ico', lambda request: HttpResponse(status=204)),
    path('admin/', admin.site.urls),
    path('api/', include('core.api.urls')),
    path('', include('core.api.urls')),  # Health check at root
]
