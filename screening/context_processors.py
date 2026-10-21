"""
Template context shared by every page.

The sign-in page has to render whether or not any provider is configured,
because a checkout without a .env still has to start. This tells the template
which routes in are actually available, so it can offer those and say plainly
why the others are absent rather than showing a button that cannot work.
"""

from django.conf import settings


def sign_in_state(request):
    return {
        "google_sign_in_configured": settings.GOOGLE_SIGN_IN_CONFIGURED,
        "microsoft_sign_in_configured": settings.MICROSOFT_SIGN_IN_CONFIGURED,
        "login_by_code_enabled": settings.ACCOUNT_LOGIN_BY_CODE_ENABLED,
    }
