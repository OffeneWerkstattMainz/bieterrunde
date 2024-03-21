#!/usr/bin/env bash

set -euo pipefail

poetry run python manage.py migrate
poetry run python manage.py collectstatic --noinput

poetry run gunicorn "$@"
