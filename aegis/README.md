# A.E.G.I.S.

This directory contains the A.E.G.I.S. experience, including the lightweight
welcome app that embeds the operator chat room directly in the console.

## Quick start (Windows)

1. From the **repository root**, double-click `Install-AEGIS.bat`.
2. When installation finishes, double-click `Launch-AEGIS.bat`.
3. In Settings, set your **Portal base** to your community's website URL.
4. Use **Test connection** to verify before using the chat.

## Unified installer (Windows)

Run from the repository root (no Python required):

```bash
powershell -NoProfile -ExecutionPolicy Bypass -File aegis\install-aegis.ps1
```

Or double-click `Install-AEGIS.bat`.

### What the installer does

- Detects a system Python installation and uses it when available.
- Otherwise, downloads a portable Python runtime into `aegis/.python`.
- Creates or reuses `aegis/.venv` for isolated dependencies.
- Installs packages from `aegis/requirements.txt`.
- Builds `aegis/dist/aegis-welcome.pyz`.
- Initializes the configuration defaults and optional desktop shortcut.

### Built-in operator chat

The welcome window includes the operator chat room directly inside the
app. Configure the chat relay in Settings:

- **Portal base** – your community's full URL (e.g. `https://yoursite.railway.app`).
- **Display name** – your handle in the chat.

Environment variables (optional):

- `AEGIS_PORTAL_URL` – base URL override.
- `AEGIS_OPERATOR_NAME` – display name override.

### Launch the welcome app

Double-click `Launch-AEGIS.bat` or run:

```bash
aegis\.venv\Scripts\python.exe aegis\dist\aegis-welcome.pyz
```
