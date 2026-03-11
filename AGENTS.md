# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

Project Spectre is a military-themed Discord community management platform with three main services:

| Service | Stack | Default Port | Run Command |
|---|---|---|---|
| FastAPI Dashboard | Python / FastAPI / Uvicorn | 8000 | `python3 -m uvicorn config_app:app --host 0.0.0.0 --port 8000` |
| Express Security API | Node.js / Express 5 | 3000 | `npm run dev` (or `npm start`) |
| Discord Bot | Python / Nextcord | — | `python main.py` (needs real `DISCORD_TOKEN`) |

### Database

PostgreSQL 16 is required. Start it with `sudo pg_ctlcluster 16 main start`. The database name is `spectre`; schema lives at `sql/schema.sql`. Apply with:

```
PGPASSWORD=postgres psql -h localhost -U postgres -d spectre -f sql/schema.sql
```

### Required environment variables for local dev

Set these before running the FastAPI dashboard or tests:

- `FORCE_LOCAL_STORAGE=1` — bypasses DigitalOcean Spaces, uses local filesystem
- `GUILD_ID=1` — placeholder Discord guild ID
- `DISCORD_BOT_TOKEN=placeholder` — satisfies import-time checks
- `RUN_DISCORD_BOT=false` — prevents bot subprocess from spawning

The Express Security API reads from `.env` (copy `.env.example`). Key vars: `DATABASE_URL`, `JWT_SECRET`, `NODE_ENV`.

### FastAPI dashboard auth

When `DASHBOARD_USERNAME` / `DASHBOARD_PASSWORD` are unset, the dashboard defaults to `admin` / `password` (HTTP Basic Auth).

### Running tests

- **Python**: `python3 -m pytest tests/ -q` (323+ tests; 4 pre-existing failures unrelated to environment)
- **Node.js lint**: `npm run lint:check`

### Gotchas

- The `config_app.py` file is ~8400 lines; it imports many local modules at startup. Ensure the workspace root is on `PYTHONPATH` or run from `/workspace`.
- Python 3.12 works fine despite `nixpacks.toml` specifying Python 3.11 for Railway.
- The `nextcord` package emits an `audioop` deprecation warning on Python 3.12+; this is harmless.
- Starlette `TemplateResponse` deprecation warnings in tests are pre-existing and not blocking.
