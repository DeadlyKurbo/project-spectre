# A.E.G.I.S.

This directory contains the A.E.G.I.S. experience, including the lightweight
welcome app that now embeds the operator chat room directly in the console.

## Unified installer (Windows)

Run the installer from the repository root (no Python required):

```bash
install-aegis.cmd
```

The installer will download dependencies, build the zipapp archive, and then
open the configuration menu so you can set operator details immediately.

### What the installer does

- Downloads a portable Python runtime into `aegis/.python` (only if missing).
- Creates or reuses `aegis/.venv` for isolated dependencies.
- Installs packages from `aegis/requirements.txt`.
- Builds `aegis/dist/aegis-welcome.pyz`.
- Launches the configuration window to capture operator name, operator ID
  code, portal base for the chat relay API, and optional desktop shortcut
  creation.

### Built-in operator chat

The welcome window now includes the operator chat room directly inside the
app, so operators can communicate without opening a browser. You can control
the chat relay endpoint by setting environment variables before launching the
app:

- `AEGIS_PORTAL_URL` – base URL (defaults to `http://localhost:8000`).
- `AEGIS_OPERATOR_NAME` – optional display name override.
- `AEGIS_OPERATOR_ID` – optional operator ID code to prefill the access check.

You can re-run the installer at any time; it will refresh dependencies and
rebuild the archive without any external packaging tools.

### Launch the welcome app

Once installed, launch the welcome app from the repository root:

```bash
aegis\.venv\Scripts\python.exe aegis\dist\aegis-welcome.pyz
```
