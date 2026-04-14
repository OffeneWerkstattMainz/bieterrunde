# ruff: noqa: F405
import os

from .settings import *  # noqa: F403


DEBUG = False
ALLOWED_HOSTS = os.environ.get("ALLOWED_HOSTS", "").split(",")

DATABASES["default"] = {
    "ENGINE": "django.db.backends.postgresql",
    "NAME": "bieterrunde",
    "USER": "postgres",
    "PASSWORD": "",
    "HOST": os.environ.get("DB_HOST", "localhost"),
    "PORT": os.environ.get("DB_PORT", "5432"),
}


MIDDLEWARE.insert(
    MIDDLEWARE.index("django.middleware.security.SecurityMiddleware"),
    "whitenoise.middleware.WhiteNoiseMiddleware",
)

INSTALLED_APPS += [
    "django_rq",
    "django_tasks_rq",
]

LOGGING["loggers"][""] = {
    "level": "INFO",
    "handlers": ["console"],
}

SECRET_KEY_FILE = Path(os.environ["SECRET_KEY_FILE"])
if not SECRET_KEY_FILE.exists():
    from django.core.management.utils import get_random_secret_key

    SECRET_KEY_FILE.write_text(get_random_secret_key())

SECRET_KEY = SECRET_KEY_FILE.read_text().strip()

STATIC_ROOT = os.environ.get("STATIC_ROOT", BASE_DIR / "static")
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

CSRF_COOKIE_SECURE = True
SESSION_COOKIE_SECURE = True

TASKS = {
    "default": {
        "BACKEND": "django_tasks_rq.RQBackend",
        "QUEUES": ["default"],
    },
}

RQ_QUEUES = {
    "default": {
        "HOST": os.environ.get("RQ_HOST"),
        "PORT": 6379,
        "DB": 0,
        "DEFAULT_TIMEOUT": 360,
        "DEFAULT_RESULT_TTL": 800,
    },
}
