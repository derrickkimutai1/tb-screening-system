"""
Hash the audit rows that were written before the chain existed.

Without this they carry empty hashes, so verification would report every one
of them as broken and the real signal would be lost in the noise.

Sealing them now is honest about what it proves, which is less than it looks:
these rows are being hashed as they stand today, so the chain attests that
nothing has changed since this migration ran, not since each row was written.
Rows written afterwards are sealed as they are inserted and carry the stronger
claim. The difference is worth knowing when reading a verification result for
a database that predates this.
"""

import hashlib

from django.db import migrations

FIELD_SEPARATOR = chr(31)

CHAINED_FIELDS = (
    "actor_id",
    "actor_label",
    "action",
    "case_id",
    "facility",
    "ip_address",
    "user_agent",
    "detail",
    "created_at",
)


def seal(apps, schema_editor):
    AccessEvent = apps.get_model("screening", "AccessEvent")

    previous = ""
    for event in AccessEvent.objects.order_by("id").iterator():
        parts = [previous]
        for name in CHAINED_FIELDS:
            value = getattr(event, name, None)
            parts.append("" if value is None else str(value))
        digest = hashlib.sha256(
            FIELD_SEPARATOR.join(parts).encode("utf-8")
        ).hexdigest()

        AccessEvent.objects.filter(pk=event.pk).update(
            previous_hash=previous, entry_hash=digest
        )
        previous = digest


def unseal(apps, schema_editor):
    AccessEvent = apps.get_model("screening", "AccessEvent")
    AccessEvent.objects.update(previous_hash="", entry_hash="")


class Migration(migrations.Migration):
    dependencies = [
        ("screening", "0011_audit_chain"),
    ]

    operations = [
        migrations.RunPython(seal, unseal),
    ]
