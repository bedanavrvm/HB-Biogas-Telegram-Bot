from django.urls import path
from . import views

urlpatterns = [
    path("cases/<uuid:farmer_id>/laf/", views.case_laf, name="portal_case_laf"),
    path("cases/<uuid:farmer_id>/laf/<uuid:version_id>/document/", views.document, name="portal_laf_document"),
    path("cases/<uuid:farmer_id>/laf/<uuid:version_id>/pages/<int:page>/", views.document, name="portal_laf_page"),
]
