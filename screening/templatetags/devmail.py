"""
Show a sign-in code on the page while there is no mail provider.

The sign-in page tells the user to check their inbox. With no EMAIL_HOST
configured nothing is ever delivered, so that instruction is wrong and the
feature looks broken. Rather than leave it wrong, the code is shown while both
of these hold:

    DEBUG is on, and
    the development mail backend is the one in use

Both are necessary. DEBUG is off in the container and in any deployment, and
configuring EMAIL_HOST selects a real backend, so together they mean nobody can
receive the message and nobody is in production.

This must never apply anywhere real: showing a sign-in code to whoever loaded
the page is handing out the account. DevelopmentCodeTests asserts it disappears
when either guard is changed.
"""

from django import template
from django.conf import settings

register = template.Library()

DEVELOPMENT_BACKEND = "screening.services.devmail.LastMessageBackend"


@register.simple_tag
def development_code():
    """The code that would have been emailed, or None when guarded off."""
    if not settings.DEBUG or settings.EMAIL_BACKEND != DEVELOPMENT_BACKEND:
        return None

    from screening.services.devmail import last_code

    return last_code()
