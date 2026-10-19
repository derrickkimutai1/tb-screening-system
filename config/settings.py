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

# No local registration. The only ways in are Google and a superuser created
# from the command line, so there is no self-service password to steal.
ACCOUNT_ADAPTER = "screening.auth.ScreeningAccountAdapter"
SOCIALACCOUNT_ADAPTER = "screening.auth.ScreeningSocialAccountAdapter"

ACCOUNT_LOGIN_METHODS = {"email"}
ACCOUNT_SIGNUP_FIELDS = ["email*"]
ACCOUNT_EMAIL_VERIFICATION = "none"
ACCOUNT_LOGOUT_ON_GET = False

# Google has already verified the address, so asking the user to confirm it
# again by email would add a step without adding assurance.
SOCIALACCOUNT_EMAIL_VERIFICATION = "none"
SOCIALACCOUNT_EMAIL_REQUIRED = True
SOCIALACCOUNT_AUTO_SIGNUP = True
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

if GOOGLE_SIGN_IN_CONFIGURED:
    SOCIALACCOUNT_PROVIDERS = {
        "google": {
            "APP": {
                "client_id": GOOGLE_OAUTH_CLIENT_ID,
                "secret": GOOGLE_OAUTH_CLIENT_SECRET,
                "key": "",
            },
            "SCOPE": ["profile", "email"],
            # No refresh token is wanted: the application acts only while the
            # user is present and never calls Google on their behalf later.
            "AUTH_PARAMS": {"access_type": "online"},
        }
    }
else:
    SOCIALACCOUNT_PROVIDERS = {}


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
