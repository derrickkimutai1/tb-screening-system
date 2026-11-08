"""
Show a sign-in code on the page as well as sending it.

The page telling a user to check an inbox is wrong when nothing can arrive,
and that is how this started: with no mail provider configured the instruction
was a lie and the feature looked broken. It now also covers the case where
mail does work and the code is wanted on screen anyway, which is what a
demonstration needs when the room's network cannot be relied on.

One setting decides it, SIGN_IN_CODE_ON_SCREEN, and DEBUG is already folded
into it where it is computed. Whether the message is also delivered is a
separate question answered by EMAIL_HOST.

This must never apply anywhere real: showing a sign-in code to whoever loaded
the page is handing out the account. DevelopmentCodeTests asserts it
disappears when DEBUG is off, whatever else is set.
"""

from django import template
from django.conf import settings

register = template.Library()


@register.simple_tag
def development_code():
    """The code from the last message, or None when it must not be shown."""
    if not getattr(settings, "SIGN_IN_CODE_ON_SCREEN", False):
        return None
    if not settings.DEBUG:
        # Belt and braces. SIGN_IN_CODE_ON_SCREEN already folds DEBUG in, but
        # a test or a future edit could set it directly, and the cost of being
        # wrong here is somebody else's account.
        return None

    from screening.services.devmail import last_code

    return last_code()
