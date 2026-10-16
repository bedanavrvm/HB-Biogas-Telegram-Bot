from django.urls import path
from . import views

urlpatterns = [
    path('', views.index, name='ui_review_lab'),
    path('api/catalogue/', views.catalogue, name='ui_review_catalogue'),
    path('api/patterns/<slug:pattern>/', views.pattern_detail, name='ui_review_pattern'),
    path('api/revisions/', views.create_revision, name='ui_review_revision'),
    path('api/revisions/<uuid:revision_id>/decisions/', views.submit_decision, name='ui_review_decision'),
    path('api/revisions/<uuid:revision_id>/evidence/', views.upload_evidence, name='ui_review_upload'),
    path('api/revisions/<uuid:revision_id>/evidence/<int:index>/', views.evidence, name='ui_review_evidence'),
    path('api/releases/', views.release, name='ui_review_release'),
    path('api/releases/<uuid:release_id>/export/', views.export_release, name='ui_review_export'),
    path('api/scenes/<slug:app>/<slug:scene>/', views.scene, name='ui_review_scene'),
]
