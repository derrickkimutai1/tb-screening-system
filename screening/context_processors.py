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
        "github_sign_in_configured": settings.GITHUB_SIGN_IN_CONFIGURED,
        "any_provider_configured": any(
            (
                settings.GOOGLE_SIGN_IN_CONFIGURED,
                settings.MICROSOFT_SIGN_IN_CONFIGURED,
                settings.GITHUB_SIGN_IN_CONFIGURED,
            )
        ),
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

    from .models import PredictionRecord, profile_for
    from .services.predict import MODEL_VERSION, PredictionEngine

    profile = profile_for(user)

    return {
        "viewer_profile": profile,
        "viewer_facility": profile.facility,
        # The count on the worklist tab. Everything the rail shows has to be
        # true on every page, so it is counted here rather than passed in by
        # the one view that happens to know it.
        "pending_review_count": (
            PredictionRecord.objects.visible_to(user).awaiting_review().count()
        ),
        # Whether a prediction could actually be served. is_available() is a
        # file check rather than a load, so this costs a stat call and not a
        # TensorFlow import; the dot in the rail says what was checked rather
        # than asserting readiness no one looked for.
        "model_installed": PredictionEngine.is_available(),
        "model_version": MODEL_VERSION,
    }


def session_timeout(request):
    """How long a signed-in session has left, for the idle warning.

    The server ends an idle session whether or not the page says anything.
    This only lets the page warn first, so work in progress can be saved
    rather than lost to a redirect.
    """
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}

    return {
        "session_idle_seconds": settings.SESSION_COOKIE_AGE,
        "session_warning_seconds": getattr(settings, "SESSION_WARNING_SECONDS", 120),
    }
