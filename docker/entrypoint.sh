#!/usr/bin/env bash

set -euo pipefail

MODE="${1:-web}"
shift

case "$MODE" in
  web)
    uv run --group prod --no-group dev python manage.py migrate
    uv run --group prod --no-group dev python manage.py collectstatic --noinput

    uv run --group prod --no-group dev gunicorn "$@"
    ;;
  worker)
    uv run --group prod --no-group dev manage.py rqworker --job-class django_tasks_rq.Job
    ;;
  *)
    echo "Unknown mode: $MODE"
    exit 1
    ;;
esac
