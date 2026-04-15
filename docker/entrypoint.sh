#!/usr/bin/env bash

set -euo pipefail

uv run --group prod --no-group dev python manage.py migrate
uv run --group prod --no-group dev python manage.py collectstatic --noinput

uv run --group prod --no-group dev gunicorn "$@"
