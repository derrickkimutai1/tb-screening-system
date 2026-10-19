"""
Give a profile to the accounts that already existed.

Profiles are created by a signal when an account is created, which covers
everything from here on. It does nothing for the accounts that were already in
the database when profiles were added, and those are exactly the ones in use:
the first Google sign-in predates this model.

Without this, opening the profile page as one of those users raises
RelatedObjectDoesNotExist, which is what happened.
"""

from django.db import migrations


def give_everyone_a_profile(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Profile = apps.get_model("screening", "Profile")

    # The historical model has no default from the field definition applied the
    # way a live model would, so the role is named here. Radiographer is the
    # least privileged of the three, which is the right default for an account
    # nobody has yet assigned a role to.
    existing = set(Profile.objects.values_list("user_id", flat=True))
    Profile.objects.bulk_create(
        [
            Profile(user_id=user_id, role="radiographer", facility="")
            for user_id in User.objects.exclude(id__in=existing).values_list("id", flat=True)
        ]
    )


def remove_them(apps, schema_editor):
    # Deliberately does nothing. Reversing this migration should not delete a
    # role an administrator has since assigned; the table itself is removed by
    # reversing 0003.
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("screening", "0003_reviewnote_reviewer_profile"),
    ]

    operations = [
        migrations.RunPython(give_everyone_a_profile, remove_them),
    ]
