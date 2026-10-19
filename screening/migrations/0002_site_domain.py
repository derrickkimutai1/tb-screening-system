"""
Name the site that sign-in runs on.

django.contrib.sites ships a single row reading "example.com". allauth uses it
when it builds the address Google returns the user to, so leaving the default
in place sends a working sign-in to a domain nobody owns. The value is read
from the environment so that a developer machine, the marking deployment and
the packaged build can each name themselves without a code change.
"""

import os

from django.db import migrations

DEFAULT_DOMAIN = "localhost:8000"


def name_the_site(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    domain = os.environ.get("DJANGO_SITE_DOMAIN", DEFAULT_DOMAIN).strip() or DEFAULT_DOMAIN
    Site.objects.update_or_create(
        pk=1,
        defaults={"domain": domain, "name": "TB Screening"},
    )


def restore_the_default(apps, schema_editor):
    Site = apps.get_model("sites", "Site")
    Site.objects.filter(pk=1).update(domain="example.com", name="example.com")


class Migration(migrations.Migration):
    dependencies = [
        ("screening", "0001_initial"),
        ("sites", "0002_alter_domain_unique"),
    ]

    operations = [
        migrations.RunPython(name_the_site, restore_the_default),
    ]
