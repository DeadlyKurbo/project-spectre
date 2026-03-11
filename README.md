# Project Spectre Workspace

This repository hosts multiple tools and utilities. The A.E.G.I.S. welcome app
lives in the [`aegis/`](aegis/) directory, along with its unified installer
scripts.


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

## Install A.E.G.I.S. (Windows)

> **Easiest:** Download `AEGIS.exe` and double-click to run. No installation, no Python, no command line.

One file does everything. See [`aegis/README.md`](aegis/README.md) for details.

### Build the EXE (developers)

From the `aegis/` folder:

```bash
cd aegis
python build_installer.py
```

This produces `dist/AEGIS.exe` to distribute to users.

### Before using the chat

1. In the A.E.G.I.S. app Settings, set the **Portal base** to your community's website URL.
2. Enter your **Display name** (username) — no password required.
3. Use "Test connection" to verify before chatting.
