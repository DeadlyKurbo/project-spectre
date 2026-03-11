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

> **Easiest:** Open the `aegis/` folder and double-click `Install-AEGIS.bat`. No command line needed.

Or run manually from the `aegis/` folder:

```bash
cd aegis
powershell -NoProfile -ExecutionPolicy Bypass -File install-aegis.ps1
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

- **Display name** (used in the on-screen greeting and chat).
- **Portal base** – your community's website URL (e.g. `https://yoursite.railway.app`). Use the "Test connection" button to verify.
- Optional **desktop shortcut** creation (Windows only).

All settings are saved to `aegis/aegis-config.json` (or `~/.aegis-config.json`
if the install directory is not writable).

### Launch the welcome app

**Easiest:** From the `aegis/` folder, double-click `Launch-AEGIS.bat`.

Or run manually from `aegis/`:

```bash
cd aegis
.venv\Scripts\python.exe dist\aegis-welcome.pyz
```

### Before using the chat

1. In the A.E.G.I.S. app Settings, set the **Portal base** to your community's website URL.
2. Enter your **Display name** (username) — no password required.
3. Use "Test connection" to verify before chatting.

### Helpful flags

- `--SkipBuild` to install dependencies without rebuilding the zipapp.
- `--SkipConfig` to skip the configuration menu (not recommended).
