"""Reviewed Telegram Web framing policy; authentication remains in each API."""
from inspect import unwrap


MINIAPP_HTML_VIEWS = {
    'core.api.views': frozenset({'tat_tracker_app', 'spin_form', 'order_approval_form',
                                 'jawabu_farmers_review', 'fca_review'}),
    'core.api.complaint_case_views': frozenset({'complaint_cases_app'}),
    'core.api.portal_views': frozenset({'portal_home', 'portal_screen', 'portal_case_history_detail',
                                      'portal_farmup_review_screen', 'portal_hb_actions_screen',
                                      'portal_invoices_screen', 'portal_payment_approvals_screen',
                                      'portal_payments_screen', 'portal_reports_screen'}),
    'origination.views': frozenset({'origination_app', 'origination_signing_app'}),
}


class MiniAppFramePolicyMiddleware:
    """Runs before XFrameOptionsMiddleware on the response path."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        match = getattr(request, 'resolver_match', None)
        if not match or not response.get('Content-Type', '').startswith('text/html'):
            return response
        view = unwrap(match.func)
        if view.__name__ not in MINIAPP_HTML_VIEWS.get(view.__module__, ()):
            return response
        directives = [part.strip() for part in response.get('Content-Security-Policy', '').split(';')
                      if part.strip() and part.strip().split()[0].lower() != 'frame-ancestors']
        directives.append("frame-ancestors 'self' https://web.telegram.org")
        response['Content-Security-Policy'] = '; '.join(directives)
        response.xframe_options_exempt = True
        if 'X-Frame-Options' in response:
            del response['X-Frame-Options']
        return response
