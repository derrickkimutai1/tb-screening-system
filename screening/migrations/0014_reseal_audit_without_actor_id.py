"""
Re-seal the audit trail, hashing who acted rather than which row they are.

The chain hashed actor_id. That column is a SET_NULL foreign key, so deleting
an account rewrote it to NULL on every row that account had ever produced, and
the hashes of those rows no longer matched their contents. Verification
correctly reported a hundred altered rows; what had altered them was an
ordinary user deletion, not an attack.

A tamper-evident chain has to hash what cannot legitimately change. actor_label
holds the address as text and nothing rewrites it, so who acted is still
covered. actor_id stays on the row, readable, outside the hash.

What this migration costs, stated plainly: every existing row is re-hashed as
it stands today, so from here the chain attests that nothing has changed since
this ran, not since each row was written. That claim is weaker than the one
the rows carried yesterday, and it is the price of having a verification result
that means something again. Rows written afterwards are sealed on insert and
carry the stronger claim.
"""

import hashlib

from django.db import migrations

FIELD_SEPARATOR = chr(31)

# Must match AccessEvent.CHAINED_FIELDS at the time this migration was written.
# Kept as its own copy rather than imported, because a migration has to keep
# describing what it did even after the model moves on.
CHAINED_FIELDS = (
    "actor_label",
    "action",
    "case_id",
    "facility",
    "ip_address",
    "user_agent",
    "detail",
    "created_at",
)


def reseal(apps, schema_editor):
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


def unreseal(apps, schema_editor):
    """Put the rows back under the old field list, actor_id included.

    Reversing this restores the earlier hashes, which means restoring the
    earlier fault as well: deleting a user will break the chain again.
    """
    AccessEvent = apps.get_model("screening", "AccessEvent")

    previous = ""
    for event in AccessEvent.objects.order_by("id").iterator():
        parts = [previous]
        for name in ("actor_id", *CHAINED_FIELDS):
            value = getattr(event, name, None)
            parts.append("" if value is None else str(value))
        digest = hashlib.sha256(
            FIELD_SEPARATOR.join(parts).encode("utf-8")
        ).hexdigest()

        AccessEvent.objects.filter(pk=event.pk).update(
            previous_hash=previous, entry_hash=digest
        )
        previous = digest


class Migration(migrations.Migration):
    dependencies = [
        ("screening", "0013_explanation_fields"),
    ]

    operations = [
        migrations.RunPython(reseal, unreseal),
    ]
