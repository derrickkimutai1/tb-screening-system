"""
Who may sign in, and how.

The application does not create accounts of its own. A clinician signs in with
a Google account they already have, Google vouches for the address, and this
module decides whether that address is admitted. Two rules apply:

Local registration is closed
    There is no username-and-password sign-up form. Without one there is no
    password for this system to store, leak or reset. Staff accounts for the
    Django admin are still created from the command line with createsuperuser.

Admission is by allowlist
    A screening record is clinical data, so a Google account alone is not a
    credential for reading it. The address must appear in SIGN_IN_ALLOWED_EMAILS
    or its domain in SIGN_IN_ALLOWED_DOMAINS. An empty allowlist admits any
    Google account; that is a convenience for a local demonstration and is
    recorded in .env.example as unsuitable for deployment.
"""

import logging

from allauth.account.adapter import DefaultAccountAdapter
from allauth.core.exceptions import ImmediateHttpResponse
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect

logger = logging.getLogger(__name__)


def address_is_allowed(email):
    """Is this address admitted by the configured allowlist?"""
    allowed_emails = getattr(settings, "SIGN_IN_ALLOWED_EMAILS", set())
    allowed_domains = getattr(settings, "SIGN_IN_ALLOWED_DOMAINS", set())

    # Nothing configured means no restriction, which is the local-demo default.
    if not allowed_emails and not allowed_domains:
        return True

    if not email:
        return False

    email = email.strip().lower()
    if email in allowed_emails:
        return True

    _, _, domain = email.partition("@")
    return bool(domain) and domain in allowed_domains


class ScreeningAccountAdapter(DefaultAccountAdapter):
    """Closes the local username-and-password sign-up route."""

    def is_open_for_signup(self, request):
        return False


class ScreeningSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Admits a Google account only if the allowlist accepts its address."""

    def is_open_for_signup(self, request, sociallogin):
        return address_is_allowed(sociallogin.user.email)

    def pre_social_login(self, request, sociallogin):
        """Applies the allowlist to returning users as well as new ones.

        is_open_for_signup is consulted only when an account is being created.
        Removing an address from the allowlist should also lock out someone who
        signed in before, so the check is repeated here on every sign-in. A
        refusal returns the user to the sign-in page with an explanation rather
        than a bare 403, which the brief asks for in section 12.
        """
        email = sociallogin.user.email or sociallogin.account.extra_data.get("email", "")
        if address_is_allowed(email):
            return
        # A refused sign-in is worth a record: it is either a misconfigured
        # allowlist or someone trying an address they should not be using.
        logger.warning("Refused sign-in for %s: not on the allowlist.", email or "(no address)")
        messages.error(
            request,
            "That Google account is not authorised for this system. "
            "Contact the administrator to be added.",
        )
        raise ImmediateHttpResponse(redirect("account_login"))
