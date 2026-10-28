"""Native operations contract; gated by browser and Complaint release flags."""
from django.urls import path
from . import browser_complaint_operations as views
from complaint_publications import views as publications

urlpatterns = [
    path('uploads/', publications.reserve),
    path('uploads/<uuid:attempt_key>/', publications.progress),
    path('uploads/<uuid:attempt_key>/<uuid:file_key>/', publications.receive),
    path('publications/attention/', publications.attention),
    path('bootstrap/', views.bootstrap),
    path('cases/', views.queue),
    path('cases/create/', views.create),
    path('cases/<uuid:case_key>/', views.detail),
    path('cases/<uuid:case_key>/publication/', publications.case_progress),
    path('cases/<uuid:case_key>/history/', views.history),
    path('cases/<uuid:case_key>/conversation/', views.conversation),
    path('cases/<uuid:case_key>/conversation/post/', views.conversation_post),
    path('cases/<uuid:case_key>/conversation/people/', views.conversation_people),
    path('cases/<uuid:case_key>/conversation/<uuid:update_key>/reaction/', views.conversation_reaction),
    path('cases/<uuid:case_key>/<slug:action>/', views.action),
    path('draft/', views.draft),
    path('locations/', views.locations),
    path('category-suggestion/', views.category_suggestion),
    path('preferences/', views.preferences),
    path('recovery/', views.recovery),
    path('voice/', views.voice),
    path('evidence/<uuid:evidence_key>/', views.evidence),
    path('evidence/<uuid:evidence_key>/preview/', views.evidence_preview),
    path('reports/', views.reports),
    path('reports/cases/<uuid:case_key>/', views.report_detail),
    path('reports/cases/<uuid:case_key>/history/', views.report_history),
    path('reports/export/', views.export),
    path('reports/email/', views.email),
    path('reports/email-settings/', views.email_settings),
]
