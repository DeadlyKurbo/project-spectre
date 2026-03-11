# A.E.G.I.S. Downloadable Welcome App

The repository includes a small desktop application for A.E.G.I.S. that greets users with a terminal-style UI and connects to the community chat. Binary artifacts are not stored in Git — build the installer locally before distributing.

## For End Users

1. **Download** `AEGIS-Setup.exe` from your community's release page.
2. **Run** the installer — double-click and choose an install location.
3. **Launch** A.E.G.I.S. from the Desktop or Start Menu shortcut.
4. **Configure** the Portal URL and your display name in Settings.

No Python installation required. The installer bundles everything needed.

## For Developers: Build the Installer

From the repository root:

```bash
cd aegis
python build_installer.py
```

This produces:

- `aegis/dist/AEGIS.exe` — Standalone launcher (no Python required)
- `aegis/dist/AEGIS-Setup.exe` — Installer to distribute to users

Distribute `AEGIS-Setup.exe` to your community. Users double-click to install.

## Run from Source (Development)

If you have Python 3 with Tkinter installed:

```bash
cd aegis
python aegis_app.py
```
