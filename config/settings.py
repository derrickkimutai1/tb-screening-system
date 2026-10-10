"""
Django settings for the TB screening and triage prototype.

Secrets and database credentials are read from a .env file that is never
committed. See .env.example for the expected keys.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(BASE_DIR / ".env")


def env_flag(name, default=False):
    """Read a boolean setting from the environment."""
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# Set by the desktop launcher when the application runs as a packaged build.
PACKAGED = env_flag("TB_PACKAGED")

# Where writable data lives. In development this is the project folder; in a
# packaged build it is a folder under the user's local application data, since
# the bundle itself is read-only.
DATA_DIR = Path(os.environ.get("TB_DATA_DIR", BASE_DIR))

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
    "screening",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "config.wsgi.application"


# PostgreSQL is the system's database. The portable desktop build uses SQLite
# instead, because a database server cannot be shipped inside a single file.
# The models and migrations are the same in both.
if os.environ.get("DJANGO_DB", "postgresql") == "sqlite":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": DATA_DIR / "screening.sqlite3",
        }
    }
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

# Uploaded X-rays and generated heatmap overlays. Only the paths are stored in
# PostgreSQL; the image data itself stays on disk.
MEDIA_URL = "media/"
MEDIA_ROOT = DATA_DIR / "media"

# The packaged build has no separate web server, so static files are served by
# the application itself from the collected bundle.
if PACKAGED:
    MIDDLEWARE.insert(1, "whitenoise.middleware.WhiteNoiseMiddleware")

# Upper bound on an accepted chest X-ray upload. Chest radiograph exports from
# the reference datasets sit well below this, so anything larger is rejected by
# the upload form before it reaches the model.
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = MAX_UPLOAD_BYTES

# Training scripts, saved models and evaluation artefacts.
ML_DIR = BASE_DIR / "ml"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
