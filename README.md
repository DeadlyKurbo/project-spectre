# Project Spectre Workspace

This repository hosts multiple tools and utilities. The A.E.G.I.S. welcome app
lives in the [`aegis/`](aegis/) directory, along with its unified installer
scripts.


## Railway deployment runtime

Railway uses `nixpacks.toml` to force a Python runtime and install dependencies
with `pip`. Start commands in both `railway.toml` and `Procfile` use
`python3 -m uvicorn` to avoid shell-level `uvicorn` path issues.

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

> **Start here:** run the installer (no Python required).

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File aegis\install-aegis.ps1
```

### What the installer does

1. Detects a system Python installation and uses it when available.
2. Otherwise, downloads a portable Python runtime into `aegis/.python`.
3. Creates or reuses `aegis/.venv`.
4. Downloads and installs dependencies from `aegis/requirements.txt`.
5. Builds the distributable `aegis/dist/aegis-welcome.pyz`.
6. Opens the A.E.G.I.S. configuration menu immediately after the downloads
   finish.

### Configuration menu

The configuration window lets you set:

- **Operator name** (used in the on-screen greeting).
- **Operator ID code** (used to verify chat access).
- **Portal base** for the chat relay API.
- Optional **desktop shortcut** creation (Windows only).

All settings are saved to `aegis/aegis-config.json` (or `~/.aegis-config.json`
if the install directory is not writable).

### Launch the welcome app

After installation, you can launch A.E.G.I.S. at any time:

```bash
aegis\.venv\Scripts\python.exe aegis\dist\aegis-welcome.pyz
```

### Helpful flags

- `--skip-build` to install dependencies without rebuilding the zipapp.
- `--skip-config` to skip the configuration menu (not recommended).
