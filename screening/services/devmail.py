"""
An email backend for working without a mail provider.

With no EMAIL_HOST configured, Django's console backend prints a message to the
server log and forgets it. That is fine for inspecting what was sent, and
useless to someone sitting in front of the browser: the page says to check an
inbox, nothing arrives, and a working feature looks broken. That is exactly
what happened the first time sign-in by code was demonstrated.

This backend prints as the console one does, and also keeps the last message,
so the sign-in page can show the code it would have sent. The page only reads
it while DEBUG is on, which is enforced there as well as here.

It is never selected in a deployment: settings choose it only when EMAIL_HOST
is absent, and a deployment that cannot send mail has a configuration problem
rather than a reason to display codes.
"""

import re
import threading

from django.core.mail.backends.console import EmailBackend as ConsoleBackend

_last = threading.local()

CODE = re.compile(r"\b(\d{6})\b")


class LastMessageBackend(ConsoleBackend):
    """Prints like the console backend, and remembers the newest message."""

    def send_messages(self, email_messages):
        for message in email_messages:
            found = CODE.search(message.body or "")
            _last.code = found.group(1) if found else None
            _last.to = list(message.to)
            _last.subject = message.subject
        return super().send_messages(email_messages)


def last_code():
    """The code in the most recent message, or None if there was none."""
    return getattr(_last, "code", None)


def last_recipient():
    recipients = getattr(_last, "to", None)
    return recipients[0] if recipients else None
