# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Bieterrunde is a Django 5 app for running solidarity-based membership fee bidding rounds (Bieterrunden). UI and data are in German. Key dependencies: django-htmx, django-guest-user, django-qr-code, django-click.

## Commands

```bash
uv sync                        # install deps
uv run pytest                  # run tests
uv run python manage.py <cmd>  # Django management commands
uv run ruff format .           # format code
```

## Code style

- Formatter: ruff format, line-length **99** (configured in pyproject.toml)
- Tests use `@pytest.mark.django_db` and live in `voting/tests.py`
- Run a single test: `uv run pytest -k "test_name"`

## Settings

- Dev: `bieterrunde/settings.py` — SQLite, DEBUG=True, ALLOWED_HOSTS=["*"]
- Prod: `bieterrunde/settings_prod.py` — PostgreSQL, WhiteNoise, secure cookies
- Env vars for prod: `SECRET_KEY_FILE`, `ALLOWED_HOSTS`, `DB_HOST`, `DB_PORT`, `STATIC_ROOT`
- Optional: `CREATE_VOTING_ACCESS_CODE`, `WEBLING_API_KEY`

## Architecture notes

- Views are HTMX-aware: check `request.htmx` before returning full vs. partial templates
- Guest users (django-guest-user) can vote without registering; convertible to real accounts
- `Voting` uses UUID primary keys
- Absent members can have bids pre-imported from CSV; `apply_absent_votes()` applies them at round creation
- Webling integration (optional HR export) requires `WEBLING_API_KEY` env var

## Git workflow

- Use feature branches: `feature/<name>`, `fix/<name>`
- Always open a pull request; don't push directly to `main`
