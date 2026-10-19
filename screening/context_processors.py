"""
Template context shared by every page.

The sign-in page has to render whether or not Google credentials are present,
because a checkout without a .env still has to start. This tells the template
which of the two states to draw.
"""

from django.conf import settings


def sign_in_state(request):
    return {"google_sign_in_configured": settings.GOOGLE_SIGN_IN_CONFIGURED}
