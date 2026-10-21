"""
Who may sign in, and how.

The application does not create accounts of its own. A clinician signs in with
a Google account they already have, Google vouches for the address, and this
module decides whether that address is admitted. Two rules apply:

Registration follows SIGN_IN_OPEN_REGISTRATION
    Open, anyone who can receive mail at an address may create an account with
    it; the six-digit code is what proves they control the inbox. Closed, only
    accounts created in advance can sign in. Which is right depends on whose
    radiographs are in the database, so both are kept and the setting decides.

    There is no password either way. Identity comes from a provider or from a
    code, so this system has none to store, leak or reset.

Admission is by allowlist
    Independent of the above. The address must appear in SIGN_IN_ALLOWED_EMAILS
    or its domain in SIGN_IN_ALLOWED_DOMAINS. An empty allowlist, which is the
    default, admits anyone. A deployment holding real patient records should
    set both this and SIGN_IN_OPEN_REGISTRATION.
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
    """Decides whether a new account may be created at all."""

    def is_open_for_signup(self, request):
        return getattr(settings, "SIGN_IN_OPEN_REGISTRATION", False)


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
