# A.E.G.I.S.

This directory contains the A.E.G.I.S. experience, including the lightweight
welcome app that now embeds the operator chat room directly in the console.

## Unified installer (Windows)

Run the installer from the repository root (no Python required):

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File aegis\install-aegis.ps1
```

The installer will download dependencies, build the zipapp archive, and
prime the configuration defaults automatically.

### What the installer does

- Detects a system Python installation and uses it when available.
- Otherwise, downloads a portable Python runtime into `aegis/.python`.
- Creates or reuses `aegis/.venv` for isolated dependencies.
- Installs packages from `aegis/requirements.txt`.
- Builds `aegis/dist/aegis-welcome.pyz`.
- Initializes the configuration defaults and optional desktop shortcut.

### Built-in operator chat

The welcome window now includes the operator chat room directly inside the
app, so operators can communicate without opening a browser. You can control
the chat relay endpoint by setting environment variables before launching the
app:

- `AEGIS_PORTAL_URL` – base URL (defaults to `http://localhost:8000`).
- `AEGIS_OPERATOR_NAME` – optional display name override.
- `AEGIS_ACCOUNT_NAME` – optional account name to prefill the login form.

You can re-run the installer at any time; it will refresh dependencies and
rebuild the archive without any external packaging tools.

### Launch the welcome app

Once installed, launch the welcome app from the repository root:

```bash
aegis\.venv\Scripts\python.exe aegis\dist\aegis-welcome.pyz
```
