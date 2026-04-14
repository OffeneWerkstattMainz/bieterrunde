# ruff: noqa: F405

from .settings import *  # noqa: F403

INSTALLED_APPS += [
    "django_tasks_db",
]

LOGGING["loggers"][""] = {
    "level": "DEBUG",
    "handlers": ["console"],
}

TASKS = {
    "default": {
        "BACKEND": "django_tasks_db.DatabaseBackend",
        "QUEUES": ["default"],
    },
}
