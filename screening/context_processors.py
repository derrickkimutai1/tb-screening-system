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
        "open_registration": settings.SIGN_IN_OPEN_REGISTRATION,
    }


def facility_state(request):
    """Whether the signed-in user has a clinic, and so sees any records.

    Visibility is scoped by facility and fails closed, so someone who has not
    set one sees nothing. That is the right default and a confusing first
    impression: an empty system looks broken rather than restricted. This lets
    the page say which it is.
    """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}

    from .models import profile_for

    return {"viewer_facility": profile_for(user).facility}
