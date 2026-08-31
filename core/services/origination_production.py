"""Read-only production readiness for enabled Origination e-signing."""

from core.production import production_security_readiness_issues


_ORIGINATION_CODES = (
    'origination-esign-',
    'conditional-approval-',
)


def origination_signing_readiness_issues(settings):
    if not bool(getattr(settings, 'ORIGINATION_ESIGN_ENABLED', False)):
        return []
    return [
        issue
        for issue in production_security_readiness_issues(settings, check_database=True)
        if issue.code.startswith(_ORIGINATION_CODES)
    ]
