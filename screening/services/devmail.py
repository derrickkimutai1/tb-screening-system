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

# Held for the process, not for the thread that sent the message.
#
# This was a threading.local, which looked right and was not: the request that
# sends the code and the request that renders the page asking for it are two
# different requests, and the development server hands them to whichever
# worker thread is free. The code was stored on one thread and read from
# another, so the panel was usually empty and the whole aid looked broken.
#
# A module-level holder is correct here because this backend only ever runs in
# a single-process development server. The lock is for tidiness rather than
# contention; two sign-ins at once would otherwise interleave the fields.
_lock = threading.Lock()
_last = {}

CODE = re.compile(r"\b(\d{6})\b")


class LastMessageBackend(ConsoleBackend):
    """Prints like the console backend, and remembers the newest message."""

    def send_messages(self, email_messages):
        for message in email_messages:
            found = CODE.search(message.body or "")
            with _lock:
                _last["code"] = found.group(1) if found else None
                _last["to"] = list(message.to)
                _last["subject"] = message.subject
        return super().send_messages(email_messages)


def last_code():
    """The code in the most recent message, or None if there was none."""
    with _lock:
        return _last.get("code")


def last_recipient():
    with _lock:
        recipients = _last.get("to")
    return recipients[0] if recipients else None


def forget():
    """Drop what is held. For tests, so one does not leak into the next."""
    with _lock:
        _last.clear()
