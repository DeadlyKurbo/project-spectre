# A.E.G.I.S. Downloadable Welcome App

The repository includes a small desktop application for A.E.G.I.S. that greets users with a terminal-style UI and connects to the community chat. Binary artifacts are not stored in Git — build the EXE locally before distributing.

## For End Users

1. **Download** `AEGIS.exe` from your community's release page.
2. **Double-click** to run. No installation needed.
3. **Configure** the Portal URL and your display name in Settings.

No Python, no installer. One file does everything.

## For Developers: Build the EXE

From the repository root:

```bash
cd aegis
python build_installer.py
```

This produces `aegis/dist/AEGIS.exe` — a single portable file. Distribute it; users double-click to run.

## Run from Source (Development)

If you have Python 3 with Tkinter installed:

```bash
cd aegis
python aegis_app.py
```
