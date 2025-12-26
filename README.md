# Project Spectre Workspace

This repository hosts multiple tools and utilities. The A.E.G.I.S. welcome app
lives in the [`aegis/`](aegis/) directory, with a single unified installer
script in the repository root.

## Install A.E.G.I.S.

> **Start here:** run the unified installer file.

```bash
python "run me to install aegis. (python)"
```

### What the installer does

1. Verifies Python 3.10+ is available.
2. Creates or reuses `aegis/.venv`.
3. Downloads and installs dependencies from `aegis/requirements.txt`.
4. Builds the distributable `aegis/dist/aegis-welcome.pyz`.
5. Opens the A.E.G.I.S. configuration menu immediately after the downloads
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
python aegis/dist/aegis-welcome.pyz
```

### Helpful flags

- `--skip-build` to install dependencies without rebuilding the zipapp.
- `--skip-config` to skip the configuration menu (not recommended).
