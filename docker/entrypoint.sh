#!/usr/bin/env bash

set -euo pipefail

uv run python manage.py migrate
uv run python manage.py collectstatic --noinput

uv run gunicorn "$@"
