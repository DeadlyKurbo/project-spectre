# Project Spectre Workspace

This repository hosts the Spectre web application, Discord integrations, and related tooling.


## Railway deployment runtime

Railway uses `nixpacks.toml` to force a Python runtime and install dependencies
with `pip`. Start commands in `nixpacks.toml`, `railway.toml`, and `Procfile` now use
`railway_entrypoint.py`, which runs Uvicorn as the primary web process and
starts the Discord bot only when a token is configured. This prevents optional
bot startup failures from taking down Railway web deployments.

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
