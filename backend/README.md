# Spiced Backend

FastAPI service backing Small-Team Mode: auth (delegated to Supabase Auth),
teams, team membership/invites, and team-project linking. Solo-Dev Mode never
talks to this service — it only exists for developers who opt into a team.

## Stack

FastAPI + SQLAlchemy + Alembic, running against a hosted Postgres instance
(Supabase). JWTs are issued by Supabase Auth; this service verifies them by
calling Supabase's `GET /auth/v1/user` rather than validating signatures
itself.

## Local setup

1. Create a virtual environment and install the package:

   ```
   cd backend
   python -m venv .venv
   .venv/Scripts/activate   # or source .venv/bin/activate on macOS/Linux
   pip install -e ".[dev]"
   ```

2. Copy `.env.example` to `.env` and fill in your own Supabase project's
   values (never commit `.env`):

   ```
   cp .env.example .env
   ```

   - `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` — from
     your Supabase project settings.
   - `DATABASE_URL` — the Supabase Postgres connection string, with the
     `postgresql://` scheme swapped for `postgresql+psycopg://` so SQLAlchemy
     uses the psycopg driver, e.g.
     `postgresql+psycopg://postgres:<password>@<host>:5432/postgres`.

3. Apply migrations:

   ```
   alembic upgrade head
   ```

4. Run the API:

   ```
   uvicorn app.main:app --reload
   ```

   The health check is at `http://127.0.0.1:8000/health`.

## Tests

```
pytest
```

Tests run against a temporary SQLite database (via a `get_db` dependency
override) and stub `get_current_user`, so they never touch the live Supabase
project or require network access.

## Notes

- Team invites: there is no email-sending infrastructure yet. Inviting
  someone who has never signed in creates a pending `team_members` row keyed
  by email (`user_id` is null). The next time any user authenticates, the
  backend attaches any pending invite rows matching their verified email to
  their user id (see `app/auth.py`).
- The service role key is read from config but not currently used by any
  endpoint — it is reserved for future admin-level Supabase Auth calls and
  must never be sent to the desktop client.
