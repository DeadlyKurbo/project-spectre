# Project Spectre Workspace

This repository hosts the Spectre web application, Discord integrations, and related tooling.

## Railway deployment runtime

Railway uses [`nixpacks.toml`](nixpacks.toml) to install **Python** (and **Node.js** for `npm ci`, so a second service can run the Express API without a separate build). Start commands in `nixpacks.toml`, [`railway.toml`](railway.toml), and [`Procfile`](Procfile) use [`railway_entrypoint.py`](railway_entrypoint.py), which runs Uvicorn as the primary web process and starts the Discord bot only when a token is configured. This prevents optional bot startup failures from taking down Railway web deployments.

### Quick setup on Railway

1. Create a project and add a **PostgreSQL** database. Copy or reference `DATABASE_URL` on your app service.
2. Connect this repo; Railway picks up `railway.toml` / Nixpacks.
3. Set variables from [`.env.example`](.env.example): S3-compatible storage credentials (or `FORCE_LOCAL_STORAGE` + volume path), Discord tokens if you run the bot, and any other secrets from your old host.
4. For the optional **Express security API**, add a **second** service from the same repository with start command `npm ci && npm start`, `NODE_ENV=production`, `DATABASE_URL` (same or different database), and `JWT_SECRET`. Apply [`sql/schema.sql`](sql/schema.sql) once, for example: `psql "$DATABASE_URL" -f sql/schema.sql` (see [`docs/security_api.md`](docs/security_api.md)).
5. Optionally run [`scripts/apply_schema.py`](scripts/apply_schema.py) if you prefer Python over `psql`. To copy specific JSON keys from a bucket into `spectre_kv`, see [`scripts/import_spectre_kv_from_s3.py`](scripts/import_spectre_kv_from_s3.py).

### Migrating from DigitalOcean

- **Postgres:** Dump/restore or re-run `sql/schema.sql`; use Railway’s `DATABASE_URL`.
- **Object storage:** Sync the bucket (e.g. rclone or `aws s3 sync`) to your new S3-compatible provider, then set `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_REGION`, and keys. Do not rely on a default object-storage endpoint in code—configure the provider you use.
- **Single-instance disk mode:** Mount a Railway volume and set `FORCE_LOCAL_STORAGE=1` with `SPECTRE_LOCAL_ROOT` (or `SPACES_ROOT`) pointing at the mount; copy files there. Not suitable for multiple replicas without shared storage.

## Persistence and storage

| Concern | Mechanism |
|--------|-----------|
| **Bot/site config** (`config/config.json` via [`config.py`](config.py)) | [`persistent_store.py`](persistent_store.py): Postgres `spectre_kv` when `DATABASE_URL` is set and `PERSISTENCE_BACKEND` is unset (auto) or `railway`; otherwise S3/local via `spaces` backend. |
| **Dossiers, guild JSON, uploads, listings** | [`storage_spaces.py`](storage_spaces.py): S3-compatible API or local filesystem (`FORCE_LOCAL_STORAGE`, `SPECTRE_LOCAL_ROOT`). |

- **Auto-detect:** When `PERSISTENCE_BACKEND` is unset and `DATABASE_URL` is present, the **railway** backend is used for `persistent_store` (not for all `storage_spaces` callers).
- **Explicit:** `PERSISTENCE_BACKEND=spaces` or `PERSISTENCE_BACKEND=railway` with `DATABASE_URL` as required.
- **Local / tests:** `sqlite:///...` is supported for `persistent_store` only.

This split is intentional: moving all object storage into Postgres would be a large, separate effort.
