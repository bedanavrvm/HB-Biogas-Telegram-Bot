"""Dormant read contract. No config.urls mount until operational acceptance."""
from django.urls import path

from . import browser_complaint_views as views


urlpatterns = [
    path('groups/', views.groups),
    path('groups/<int:group_key>/cases/', views.cases),
    path('groups/<int:group_key>/cases/<uuid:case_key>/', views.detail),
]
