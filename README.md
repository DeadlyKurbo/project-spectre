# Project Spectre Workspace

This repository hosts the Spectre web application, Discord integrations, and related tooling.


## Railway deployment runtime

Railway uses `nixpacks.toml` to force a Python runtime and install dependencies
with `pip`. Start commands in `nixpacks.toml`, `railway.toml`, and `Procfile` now use
`railway_entrypoint.py`, which runs Uvicorn as the primary web process and
starts the Discord bot only when a token is configured. This prevents optional
bot startup failures from taking down Railway web deployments.

### Scheduled process restarts

The runtime now supports full-process restarts (web + bot) so memory is reset
without waiting for a manual redeploy:

- `SPECTRE_PROCESS_RESTART_DAYS` (default `7`): when the interval is reached,
  `railway_entrypoint.py` shuts down child processes and exits with code `0`.
  Railway then starts a fresh container.
- `SPECTRE_AUTO_RESTART_DAYS` (default `3`): existing in-process Discord bot
  recycle inside `spectre/runtime.py`.
- `SPECTRE_PROCESS_RESTART_DAYS=off`: disables process-level restarts.

Restart metadata is written to `system/restart_state.json` in the configured
`persistent_store` backend when `DATABASE_URL` is set, with local file fallback
to `Temp/bot_restart_state.json`.

### Optional weekly Railway redeploy workflow

`.github/workflows/railway-weekly-redeploy.yml` provides a platform-level backup
redeploy each Sunday at `04:00 UTC`.

Configure repository secrets:

- `RAILWAY_TOKEN`
- `RAILWAY_PROJECT_ID`
- `RAILWAY_ENVIRONMENT_ID`
- `RAILWAY_SERVICE_ID`

Set repository variable `RAILWAY_WEEKLY_REDEPLOY_ENABLED=false` to disable.

## Persistence backend roadmap (Spaces -> Railway)

The project now includes a backend abstraction in `persistent_store.py` so
persistent data can migrate safely from object storage to database storage.

- Default backend: `PERSISTENCE_BACKEND=spaces` (or unset), using existing
  `storage_spaces` behavior.
- Railway backend:
  - Explicit: `PERSISTENCE_BACKEND=railway` with `DATABASE_URL` set.
  - Auto-detect: when `PERSISTENCE_BACKEND` is unset but `DATABASE_URL` is
    present, the Railway backend is selected automatically. This is ideal for
    hosted deployments where the platform injects `DATABASE_URL`.
  - `sqlite:///...` is supported for local validation and tests.
  - `postgres://` / `postgresql://` are supported via `asyncpg`.

This is intentionally incremental so modules can be moved one-by-one without
service disruption.

## Admin moderation platform

The moderation overhaul introduces a dedicated API and admin SPA:

- API: `/api/moderation/*`
- Admin entrypoint: `/admin`
- Legacy admin fallback: `/admin/legacy`
- PostgreSQL schema: `sql/moderation_schema.sql`

See `docs/admin-moderation-runbook.md` for migration, rollout, and verification steps.
