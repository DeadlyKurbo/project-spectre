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

### Full cutover from DigitalOcean (everything on Railway)

Railway gives you **compute + Postgres**. It does **not** host S3-style object storage, so dossiers and uploads must live in **another S3-compatible bucket** (e.g. Cloudflare R2, AWS S3) or on a **Railway volume** with `FORCE_LOCAL_STORAGE` (single replica).

**Order of operations**

1. **Postgres (if you use DigitalOcean Managed Database)**  
   `pg_dump "$DO_DATABASE_URL" -Fc -f backup.dump` then `pg_restore -d "$DATABASE_URL" backup.dump` using Railway’s `DATABASE_URL`. If this is a fresh Railway DB, also run [`sql/schema.sql`](sql/schema.sql) once if you use the Node security API.

2. **Spaces → new bucket**  
   Sync with [rclone](https://rclone.org/) or `aws s3 sync` (source endpoint `https://ams3.digitaloceanspaces.com` or your region). Keep the same key layout; preserve `S3_ROOT_PREFIX` semantics when configuring the app.

3. **Railway app service**  
   New service from this repo → reference `DATABASE_URL` from Railway Postgres. Set **new** `S3_*` / `AWS_*` for the destination bucket (not DigitalOcean). Copy Discord and other secrets from DO.

4. **Optional**  
   If `config/config.json` lived only in Spaces and you want it in `spectre_kv`, run [`scripts/import_spectre_kv_from_s3.py`](scripts/import_spectre_kv_from_s3.py) once with both `DATABASE_URL` and source S3 env (or after step 2 against the new bucket).

5. **Verify**  
   Open the site, list a dossier category, bot commands if applicable. Then turn off DO App/Droplet/Spaces billing when happy.

**Disk-only alternative (no cloud bucket)**  
 Mount a volume, set `FORCE_LOCAL_STORAGE=1` and `SPECTRE_LOCAL_ROOT` to the mount, copy the old bucket tree onto it. One replica unless you add shared storage elsewhere.

## Persistence and storage

| Concern | Mechanism |
|--------|-----------|
| **Bot/site config** (`config/config.json` via [`config.py`](config.py)) | [`persistent_store.py`](persistent_store.py): Postgres `spectre_kv` when `DATABASE_URL` is set and `PERSISTENCE_BACKEND` is unset (auto) or `railway`; otherwise S3/local via `spaces` backend. |
| **Dossiers, guild JSON, uploads, listings** | [`storage_spaces.py`](storage_spaces.py): S3-compatible API or local filesystem (`FORCE_LOCAL_STORAGE`, `SPECTRE_LOCAL_ROOT`). |

- **Auto-detect:** When `PERSISTENCE_BACKEND` is unset and `DATABASE_URL` is present, the **railway** backend is used for `persistent_store` (not for all `storage_spaces` callers).
- **Explicit:** `PERSISTENCE_BACKEND=spaces` or `PERSISTENCE_BACKEND=railway` with `DATABASE_URL` as required.
- **Local / tests:** `sqlite:///...` is supported for `persistent_store` only.

This split is intentional: moving all object storage into Postgres would be a large, separate effort.
