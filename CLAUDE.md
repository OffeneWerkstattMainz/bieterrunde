# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

OWM Vereinsportal is a Django 5 backend for club-related tasks of Offene Werkstatt Mainz e.V. Each task is its own Django app:

- `core` — start page (`/`), shared base template (`core/base.html`), static assets, form templates, context processors
- `voting` — Bieterrunde: solidarity-based membership fee bidding rounds, mounted at `/bieterrunde/` (legacy root URLs redirect there)
- `signup` — double opt-in for members created by the Webling WordPress plugin form, mounted at `/anmeldung/`; the task `process_signups` polls Webling, scheduled by RQ cron in `owm_portal/cron.py` (confirmation = group membership, deadlines from Webling `meta.created`; `PendingSignup` only records sent mails)

The Django project package is `owm_portal/`. UI and data are in German. Key dependencies: django-htmx, django-guest-user, django-qr-code, django-click.

## Commands

```bash
mise install                   # Install system deps
uv sync                        # install deps
uv run pytest                  # run tests
uv run python manage.py <cmd>  # Django management commands
prek run                       # run all pre-commit checks (ruff lint+format, trailing whitespace, etc.)
```

## Code style

- Formatter: ruff format, line-length **99** (configured in pyproject.toml)
- Tests use `@pytest.mark.django_db` and live in `<app>/tests.py`
- Run a single test: `uv run pytest -k "test_name"`

## Settings

- Dev: `owm_portal/settings.py` — SQLite, DEBUG=True, ALLOWED_HOSTS=["*"]
- Prod: `owm_portal/settings_prod.py` — PostgreSQL, WhiteNoise, secure cookies
- Env vars for prod: `SECRET_KEY_FILE`, `ALLOWED_HOSTS`, `DB_HOST`, `DB_PORT`, `DB_NAME` (default `owm_portal`), `STATIC_ROOT`
- Optional: `CREATE_VOTING_ACCESS_CODE`, `WEBLING_API_KEY`, `SIGNUP_*` (see README), `SMTP_*`, `EMAIL_FROM`

## Architecture notes

- New apps: extend `core/base.html`, mount under their own URL prefix in `owm_portal/urls.py`, and add an entry to the module list in `core/views.py`
- Never rename the `voting` app label: tables and migrations depend on it

- Views are HTMX-aware: check `request.htmx` before returning full vs. partial templates
- Guest users (django-guest-user) can vote without registering; convertible to real accounts
- `Voting` uses UUID primary keys
- Absent members can have bids pre-imported from CSV; `apply_absent_votes()` applies them at round creation
- Webling integration requires `WEBLING_API_KEY` env var; the shared client lives in `core/webling_api.py`

## Git workflow

- Use feature branches: `feature/<name>`, `fix/<name>`
- Always open a pull request; don't push directly to `main`
