"""
Keep a profile alongside every account.

A profile holds what Google cannot tell us: the role this person holds here and
the facility they work at. Creating it the moment the account exists means no
view, template or query has to cope with a user who has none, which is the kind
of absence that otherwise turns up as a crash on one page months later.
"""

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Profile


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.get_or_create(user=instance)
