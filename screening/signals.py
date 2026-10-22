"""
Keep a profile alongside every account.

A profile holds what Google cannot tell us: the role this person holds here and
the facility they work at. Creating it the moment the account exists means no
view, template or query has to cope with a user who has none, which is the kind
of absence that otherwise turns up as a crash on one page months later.
"""

from allauth.account.signals import user_logged_in, user_logged_out
from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import AccessEvent, Profile, profile_for


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)


@receiver(user_logged_in)
def record_sign_in(sender, request, user, **kwargs):
    """A session beginning is the first line of any access trail.

    Taken from allauth's signal rather than Django's, because every route into
    this system goes through allauth: a provider, a one-time code, or the
    first confirmation of a new address.
    """
    AccessEvent.record(
        request,
        AccessEvent.Action.SIGNED_IN,
        facility=profile_for(user).facility,
        detail=kwargs.get("signup") and "first sign-in" or "",
    )


@receiver(user_logged_out)
def record_sign_out(sender, request, user, **kwargs):
    if user is None:
        return
    AccessEvent.record(
        request,
        AccessEvent.Action.SIGNED_OUT,
        facility=profile_for(user).facility,
    )
