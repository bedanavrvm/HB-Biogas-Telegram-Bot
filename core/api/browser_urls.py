"""Intentional root-level browser and Telegram Mini App entry points."""

from django.urls import path

from .complaint_case_views import complaint_cases_app
from .origination_views import origination_app, origination_signing_app
from .portal_views import (
    portal_case_history_detail,
    portal_home,
    portal_invoices_screen,
    portal_reports_screen,
    portal_screen,
)
from .views import (
    fca_review,
    health_check,
    jawabu_farmers_review,
    order_approval_form,
    spin_form,
    staff_telegram_activation_page,
    tat_tracker_app,
)


urlpatterns = [
    path('health/', health_check, name='root_health_check'),
    path('staff/activate/', staff_telegram_activation_page, name='staff_telegram_activation_page'),
    path('origination/', origination_app, name='loan_origination_app'),
    path('s/', origination_signing_app, name='loan_origination_signing_short_app'),
    path('origination/sign/', origination_signing_app, name='loan_origination_signing_app'),
    path('order-approval/', order_approval_form, name='order_approval_form'),
    path('jawabu-farmers/review/', jawabu_farmers_review, name='jawabu_farmers_review'),
    path('fca/review/', fca_review, name='fca_review'),
    path('spin/', spin_form, name='spin_form'),
    path('tat-tracker/', tat_tracker_app, name='tat_tracker_app'),
    path('complaints/', complaint_cases_app, name='complaint_cases_app'),
    path('portal/', portal_home, name='portal_home'),
    path('portal/cases/<str:farmer_id>/', portal_case_history_detail, name='portal_case_history_detail'),
    path('portal/s/reports/', portal_reports_screen, name='portal_reports_screen'),
    path('portal/s/reports/new/', portal_reports_screen, {'report_view': 'edit'}, name='portal_reports_new'),
    path('portal/s/reports/new/<str:report_step>/', portal_reports_screen, {'report_view': 'edit'}, name='portal_reports_new_step'),
    path('portal/s/reports/<str:report_id>/', portal_reports_screen, {'report_view': 'detail'}, name='portal_report_screen_detail'),
    path('portal/s/reports/<str:report_id>/edit/', portal_reports_screen, {'report_view': 'edit'}, name='portal_report_screen_edit'),
    path('portal/s/reports/<str:report_id>/edit/<str:report_step>/', portal_reports_screen, {'report_view': 'edit'}, name='portal_report_screen_edit_step'),
    path('portal/s/reports/<str:report_id>/run/', portal_reports_screen, {'report_view': 'run'}, name='portal_report_screen_run'),
    path('portal/s/invoices/', portal_invoices_screen, name='portal_invoices_screen'),
    path('portal/s/invoices/matched/', portal_invoices_screen, {'invoice_view': 'matched'}, name='portal_invoices_matched'),
    path('portal/s/invoices/ignored/', portal_invoices_screen, {'invoice_view': 'ignored'}, name='portal_invoices_ignored'),
    path('portal/s/invoices/all/', portal_invoices_screen, {'invoice_view': 'all'}, name='portal_invoices_all'),
    path('portal/s/invoices/name-changes/', portal_invoices_screen, {'invoice_view': 'name_changes'}, name='portal_invoice_name_changes_screen'),
    path('portal/s/invoices/upload/', portal_invoices_screen, {'invoice_view': 'upload'}, name='portal_invoices_upload'),
    path('portal/s/invoices/<str:invoice_id>/', portal_invoices_screen, {'invoice_view': 'detail'}, name='portal_invoice_screen_detail'),
    path('portal/s/<str:screen>/', portal_screen, name='portal_screen'),
]
