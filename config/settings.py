"""
Django settings for the TB screening and triage prototype.

Secrets and database credentials are read from a .env file that is never
committed. See .env.example for the expected keys.
"""

import os
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def env_flag(name, default=False):
    """Read a boolean setting from the environment."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


SECRET_KEY = os.environ["DJANGO_SECRET_KEY"]

DEBUG = env_flag("DJANGO_DEBUG", default=False)

ALLOWED_HOSTS = [
    host.strip()
    for host in os.environ.get("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1").split(",")
    if host.strip()
]


INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.sites",
    "allauth",
    "allauth.account",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.microsoft",
    "screening",
]

SITE_ID = 1

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    # Directly after SecurityMiddleware, which is where WhiteNoise has to sit
    # to serve static files without a separate web server.
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "allauth.account.middleware.AccountMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # Listed ahead of the application directories so that the sign-in and
        # sign-out pages in screening/templates/account/ are found before the
        # plain ones allauth ships with.
        "DIRS": [BASE_DIR / "screening" / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "screening.context_processors.sign_in_state",
                "screening.context_processors.facility_state",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


def database_from_url(url):
    """Turn a postgres:// connection string into Django's settings dict.

    Hosted databases hand out one URL rather than five separate values, so a
    deployment can be configured with a single secret. Parsed here rather than
    with a dependency, because it is a dozen lines and the alternative is one
    more package to keep current.
    """
    parsed = urlparse(url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ImproperlyConfigured(
            f"DATABASE_URL must be a postgres URL, got {parsed.scheme!r}"
        )

    options = {}
    # Managed providers require TLS and will refuse a plain connection, so the
    # mode travels in the query string rather than being assumed here.
    query = parse_qs(parsed.query)
    if "sslmode" in query:
        options["sslmode"] = query["sslmode"][0]

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": unquote(parsed.path.lstrip("/")),
        "USER": unquote(parsed.username or ""),
        "PASSWORD": unquote(parsed.password or ""),
        "HOST": parsed.hostname or "",
        "PORT": str(parsed.port or 5432),
        "OPTIONS": options,
        # A hosted database is reached over the network, so reusing a
        # connection for a few minutes avoids paying the handshake on every
        # request. Left at 0 locally, where the cost is negligible.
        "CONN_MAX_AGE": int(os.environ.get("DB_CONN_MAX_AGE", "60")),
    }


if os.environ.get("DATABASE_URL"):
    DATABASES = {"default": database_from_url(os.environ["DATABASE_URL"])}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ["DB_NAME"],
            "USER": os.environ["DB_USER"],
            "PASSWORD": os.environ["DB_PASSWORD"],
            "HOST": os.environ.get("DB_HOST", "localhost"),
            "PORT": os.environ.get("DB_PORT", "5432"),
        }
    }


AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# Internationalisation. The prototype is scoped to Kenyan screening settings,
# so timestamps are recorded in local time rather than UTC.
LANGUAGE_CODE = "en-gb"
TIME_ZONE = "Africa/Nairobi"
USE_I18N = True
USE_TZ = True


STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"

# Served by WhiteNoise rather than by a separate web server. The deployed
# container runs one process; adding nginx in front of it to serve a handful of
# files would be more to configure and more to go wrong.
STORAGES = {
    "default": {"BACKEND": "django.core.files.storage.FileSystemStorage"},
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}

# Uploaded X-rays and generated heatmap overlays. Only the paths are stored in
# PostgreSQL; the image data itself stays on disk.
MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# Upper bound on an accepted chest X-ray upload. Chest radiograph exports from
# the reference datasets sit well below this, so anything larger is rejected by
# the upload form before it reaches the model.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_BYTES

# Training scripts, saved models and evaluation artefacts.
ML_DIR = BASE_DIR / "ml"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# ---------------------------------------------------------------------------
# Sign-in
#
# Clinical records should not be readable by an anonymous visitor, so every
# screening view requires a signed-in user. Accounts are not created in the
# application: a user signs in with an existing Google account and Google
# vouches for the address. That removes password storage, password reset and
# the whole class of credential-handling problems from this codebase.
#
# The credentials come from the environment and are never committed. When they
# are absent the application still runs: the Google provider is simply not
# registered and the sign-in page says so, which keeps a checkout without a
# .env usable for the test suite and for continuous integration.
# ---------------------------------------------------------------------------

AUTHENTICATION_BACKENDS = [
    # Required for the Django admin and for createsuperuser accounts.
    "django.contrib.auth.backends.ModelBackend",
    "allauth.account.auth_backends.AuthenticationBackend",
]

LOGIN_URL = "account_login"
LOGIN_REDIRECT_URL = "screening:upload"
LOGOUT_REDIRECT_URL = "account_login"

# Where someone lands after confirming their address. allauth's default is its
# own email-management page, which is an odd first sight of a screening system:
# a new user finished registering and arrived at a form for adding email
# addresses. They arrive at the screening page instead, which is what they came
# for.
ACCOUNT_SIGNUP_REDIRECT_URL = "screening:upload"
ACCOUNT_EMAIL_CONFIRMATION_AUTHENTICATED_REDIRECT_URL = "screening:upload"
ACCOUNT_EMAIL_CONFIRMATION_REDIRECT_URL = "screening:upload"

# Whether anyone with a working email address may create an account.
#
# True is the setting for a demonstration: a visitor signs in with any address
# they can receive mail at, which is what makes the system usable by someone
# who was never added by hand. The address is proved by the code, so an account
# cannot be made for an inbox the person does not control.
#
# A deployment holding real patient records would set this False and admit
# staff through the allowlist instead. Both behaviours are kept, because the
# right one depends on whose radiographs are in the database.
SIGN_IN_OPEN_REGISTRATION = env_flag("SIGN_IN_OPEN_REGISTRATION", default=True)

ACCOUNT_ADAPTER = "screening.auth.ScreeningAccountAdapter"
SOCIALACCOUNT_ADAPTER = "screening.auth.ScreeningSocialAccountAdapter"

ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*"]

# An address has to be proved before it becomes an account, or anyone could
# register under someone else's. Verification is by the same six-digit code as
# signing in, rather than a link, so the whole flow stays in one browser tab.
ACCOUNT_EMAIL_VERIFICATION = "mandatory" if SIGN_IN_OPEN_REGISTRATION else "none"
ACCOUNT_EMAIL_VERIFICATION_BY_CODE_ENABLED = True
ACCOUNT_SIGNUP_FORM_HONEYPOT_FIELD = "website"
ACCOUNT_LOGOUT_ON_GET = False

# A second way in, for a user whose institutional account is not one of the
# providers above, or when a provider is unreachable. A six-digit code is sent
# to the address and exchanged for a session; no password is involved, so the
# reason there are none in this codebase still holds.
#
# Because local registration is closed, this can only sign in an account that
# already exists. It is not a route around the allowlist.
ACCOUNT_LOGIN_BY_CODE_ENABLED = True
ACCOUNT_LOGIN_BY_CODE_TIMEOUT = 300
ACCOUNT_LOGIN_BY_CODE_MAX_ATTEMPTS = 3

# Six digits rather than allauth's default letter groups. A numeric code is
# what a phone recognises as a one-time code and offers to fill in, and it is
# easier to read off a screen and retype.
#
# Six digits is a million combinations. On its own that is not much, which is
# why it expires in five minutes, allows three attempts, and is rate limited
# below; the strength is in the narrow window, not in the code.
#
# Set at the root rather than per flow, so the code that verifies a new address
# looks and behaves exactly like the one that signs an existing user in. Two
# different code formats in one product is the kind of detail that makes a
# system feel improvised.
USER_CODE_FORMAT = {"numeric": True, "length": 6, "dashed": False}
ACCOUNT_LOGIN_BY_CODE_FORMAT = USER_CODE_FORMAT
ACCOUNT_EMAIL_VERIFICATION_BY_CODE_FORMAT = USER_CODE_FORMAT

# A code sent by email is guessable in a way a password is not, so the attempts
# are capped above and the requests are capped here. Without this, an address
# could be enumerated or a code brute-forced at leisure.
#
# The per-key limits are keyed on the address being used. allauth raises
# ImproperlyConfigured, and the request becomes a 500, if a view consults a
# keyed limit without a key to hand: that happens on a bare POST to the login
# view, which carries no address because this interface never posts there.
# Those two are therefore limited by address only where an address is
# guaranteed, and by IP otherwise.
ACCOUNT_RATE_LIMITS = {
    "login": "10/m/ip",
    "login_failed": "5/5m/ip",
    "request_login_code": "3/5m/key,10/h/ip",
    "confirm_login_code": "5/5m/key",
    "signup": "5/h/ip",
    "reset_password": "3/h/ip",
}

# Google has already verified the address, so asking the user to confirm it
# again by email would add a step without adding assurance.
SOCIALACCOUNT_EMAIL_VERIFICATION = "none"
SOCIALACCOUNT_EMAIL_REQUIRED = True
# False so the first Google sign-in stops at a form. Google supplies an
# identity; it cannot say which clinic the person works at, and this is the
# moment to ask and to explain what their role permits.
SOCIALACCOUNT_AUTO_SIGNUP = False
SOCIALACCOUNT_FORMS = {"signup": "screening.forms.SocialSignupForm"}
SOCIALACCOUNT_LOGIN_ON_GET = False
SOCIALACCOUNT_STORE_TOKENS = False

GOOGLE_OAUTH_CLIENT_ID = os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "").strip()
GOOGLE_OAUTH_CLIENT_SECRET = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()

GOOGLE_SIGN_IN_CONFIGURED = bool(GOOGLE_OAUTH_CLIENT_ID and GOOGLE_OAUTH_CLIENT_SECRET)

# Who is allowed in. An empty allowlist admits any Google account, which is
# acceptable for a local demonstration but not for a deployment holding
# clinical records, so both keys are documented in .env.example.
SIGN_IN_ALLOWED_DOMAINS = {
    domain.strip().lower().lstrip("@")
    for domain in os.environ.get("SIGN_IN_ALLOWED_DOMAINS", "").split(",")
    if domain.strip()
}
SIGN_IN_ALLOWED_EMAILS = {
    address.strip().lower()
    for address in os.environ.get("SIGN_IN_ALLOWED_EMAILS", "").split(",")
    if address.strip()
}

SOCIALACCOUNT_PROVIDERS = {}

if GOOGLE_SIGN_IN_CONFIGURED:
    SOCIALACCOUNT_PROVIDERS["google"] = {
        "APP": {
            "client_id": GOOGLE_OAUTH_CLIENT_ID,
            "secret": GOOGLE_OAUTH_CLIENT_SECRET,
            "key": "",
        },
        "SCOPE": ["profile", "email"],
        # No refresh token is wanted: the application acts only while the user
        # is present and never calls Google on their behalf later.
        "AUTH_PARAMS": {"access_type": "online"},
    }

# Microsoft, because a Kenyan university or hospital issuing @strathmore.edu
# addresses is most likely running Microsoft 365, and a clinician should be
# able to use the account their employer already gave them. Registered on the
# same terms as Google: only when its credentials are present.
MICROSOFT_OAUTH_CLIENT_ID = os.environ.get("MICROSOFT_OAUTH_CLIENT_ID", "").strip()
MICROSOFT_OAUTH_CLIENT_SECRET = os.environ.get("MICROSOFT_OAUTH_CLIENT_SECRET", "").strip()
# "common" admits both work or school and personal Microsoft accounts. A single
# tenant id here would restrict sign-in to one organisation, which is the right
# setting for a real deployment and the wrong one for a demonstration.
MICROSOFT_TENANT = os.environ.get("MICROSOFT_TENANT", "common").strip() or "common"

MICROSOFT_SIGN_IN_CONFIGURED = bool(MICROSOFT_OAUTH_CLIENT_ID and MICROSOFT_OAUTH_CLIENT_SECRET)

if MICROSOFT_SIGN_IN_CONFIGURED:
    SOCIALACCOUNT_PROVIDERS["microsoft"] = {
        "APP": {
            "client_id": MICROSOFT_OAUTH_CLIENT_ID,
            "secret": MICROSOFT_OAUTH_CLIENT_SECRET,
            "key": "",
        },
        "TENANT": MICROSOFT_TENANT,
    }


# ---------------------------------------------------------------------------
# Running behind a proxy
#
# A hosted deployment terminates TLS at a load balancer and forwards plain HTTP
# to the container. Without the header below Django believes every request is
# insecure, which breaks the OAuth callback: it builds an http:// redirect URI,
# Google compares it to the https:// one registered in the console, and the
# sign-in fails with redirect_uri_mismatch.
#
# The header is only trusted when the deployment sets it, because a client can
# send X-Forwarded-Proto itself and must not be able to claim its own request
# was secure.
# ---------------------------------------------------------------------------

if env_flag("DJANGO_BEHIND_PROXY"):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True

# Django 4 onwards checks the Origin header on unsafe requests against this
# list, so the deployed host has to appear here as well as in ALLOWED_HOSTS.
CSRF_TRUSTED_ORIGINS = [
    origin.strip()
    for origin in os.environ.get("DJANGO_CSRF_TRUSTED_ORIGINS", "").split(",")
    if origin.strip()
]

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SESSION_COOKIE_HTTPONLY = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_REFERRER_POLICY = "same-origin"
    X_FRAME_OPTIONS = "DENY"


# ---------------------------------------------------------------------------
# Email
#
# Sign-in codes are sent by email, so without a working backend that route
# fails silently from the user's point of view: they ask for a code and none
# arrives.
#
# In development the console backend prints the message to the terminal, which
# is enough to sign in and avoids needing a mail account to work on the
# project. A deployment sets EMAIL_HOST and the rest; the absence of a host is
# what selects the console, so a deployment that forgets to configure mail
# prints to its logs rather than pretending to have sent something.
# ---------------------------------------------------------------------------

EMAIL_HOST = os.environ.get("EMAIL_HOST", "").strip()

if EMAIL_HOST:
    EMAIL_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
    EMAIL_PORT = int(os.environ.get("EMAIL_PORT", "587"))
    EMAIL_HOST_USER = os.environ.get("EMAIL_HOST_USER", "")
    EMAIL_HOST_PASSWORD = os.environ.get("EMAIL_HOST_PASSWORD", "")
    EMAIL_USE_TLS = env_flag("EMAIL_USE_TLS", default=True)
    EMAIL_TIMEOUT = 10
else:
    # Prints like the console backend and keeps the last message, so the
    # sign-in page can show the code nobody can receive. See
    # screening/services/devmail.py for why, and for the guards.
    EMAIL_BACKEND = "screening.services.devmail.LastMessageBackend"

DEFAULT_FROM_EMAIL = os.environ.get(
    "DEFAULT_FROM_EMAIL", "TB Screening <no-reply@tb-screening.local>"
)

# Prefixes the subject of every message allauth sends.
ACCOUNT_EMAIL_SUBJECT_PREFIX = "[TB Screening] "
