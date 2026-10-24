"""
Signing in on a machine with no identity provider to ask.

The deployed system authenticates through Google, Microsoft or a code sent by
email. A packaged build reaches none of them: it runs on one laptop, possibly
in a clinic with no connection, which is the point of shipping it as a file.

So the packaged build does not ask. The person at the keyboard is the operator,
and the boundary protecting the records is the one already around their
Windows account and their local data folder; a second password typed into an
application running on their own machine would protect nothing it does not
already protect, and would be one more thing to lose.

What is not given up is the audit trail. The operator is a real account with a
real row, so every screening and review is still attributed, timed and logged.
It simply records that the work was done at this installation rather than by
someone a provider vouched for, which is the truth.

This middleware does nothing at all unless TB_PACKAGED is set, so the deployed
system is unaffected by its presence.
"""

from django.conf import settings
from django.contrib.auth import get_user_model, login

LOCAL_USERNAME = "local-operator"
LOCAL_EMAIL = "operator@localhost"
LOCAL_FACILITY = "This installation"


class PackagedOperatorMiddleware:
    """Signs the local operator in, for the packaged build only."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if settings.PACKAGED and not request.user.is_authenticated:
            operator = self.operator()
            if operator is not None:
                login(
                    request,
                    operator,
                    backend="django.contrib.auth.backends.ModelBackend",
                )
        return self.get_response(request)

    @staticmethod
    def operator():
        """The local account, created on first run.

        An administrator, because there is nobody else here to assign a role
        and the operator has to be able to review what they screen. Given a
        facility so that record scoping behaves exactly as it does on the
        server rather than being special-cased.
        """
        from screening.models import Facility, Profile, profile_for

        User = get_user_model()
        operator, created = User.objects.get_or_create(
            username=LOCAL_USERNAME,
            defaults={
                "email": LOCAL_EMAIL,
                "first_name": "Local",
                "last_name": "Operator",
            },
        )
        if created:
            # No usable password: this account is reachable only from the
            # machine it was made on, and never by signing in.
            operator.set_unusable_password()
            operator.save(update_fields=["password"])

        profile = profile_for(operator)
        changed = []
        if profile.role != Profile.Role.ADMINISTRATOR:
            profile.role = Profile.Role.ADMINISTRATOR
            changed.append("role")
        if profile.facility is None:
            profile.facility = Facility.objects.get_or_create(name=LOCAL_FACILITY)[0]
            changed.append("facility")
        if changed:
            profile.save(update_fields=[*changed, "updated_at"])

        return operator
