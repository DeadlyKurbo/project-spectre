# A.E.G.I.S.

This directory contains the A.E.G.I.S. experience, including the lightweight
welcome app that links operators into the A.L.I.C.E. flow.

## Unified installer

Run the single installer from the repository root:

```bash
python "run me to install aegis. (python)"
```

The installer will download dependencies, build the zipapp archive, and then
open the configuration menu so you can set operator details immediately.

### What the installer does

- Verifies Python 3.10+ is available.
- Creates or reuses `aegis/.venv` for isolated dependencies.
- Installs packages from `aegis/requirements.txt`.
- Builds `aegis/dist/aegis-welcome.pyz`.
- Launches the configuration window to capture operator name, portal base,
  chat URL, A.L.I.C.E. URL, and optional desktop shortcut creation.

### Welcome app quick links

The welcome window now includes buttons that open the operator chat and the
A.L.I.C.E. experience in your default browser. You can control where those
buttons point by setting environment variables before launching the app:

- `AEGIS_PORTAL_URL` – base URL (defaults to `http://localhost:8000`).
- `AEGIS_CHAT_URL` – full chat URL (defaults to `<AEGIS_PORTAL_URL>/chat`).
- `AEGIS_ALICE_URL` – full A.L.I.C.E. URL (defaults to
  `<AEGIS_PORTAL_URL>/alice`).

You can re-run the installer at any time; it will refresh dependencies and
rebuild the archive without any external packaging tools.

### Launch the welcome app

Once installed, launch the welcome app from the repository root:

```bash
python aegis/dist/aegis-welcome.pyz
```
