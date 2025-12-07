# A.E.G.I.S.

This repository hosts the A.E.G.I.S. experience, including the lightweight
welcome app that links operators into the A.L.I.C.E. flow.

## Windows quick installer

Windows users can install and launch the welcome app directly from File
Explorer without additional tooling.

1. Locate `installers/install_aegis_windows.ps1` in the repository and run it
   (double-click or right-click → **Run with PowerShell**).
2. Approve the User Account Control prompt so the installer can create files in
   the destination folder.
3. Pick your installation directory when prompted. The script copies the
   built `aegis-welcome.pyz` there and drops `Launch-AEGIS.bat` /
   `Launch-AEGIS.ps1` shortcuts.
4. Choose whether to place an A.E.G.I.S. launcher on your desktop. The
   installer defaults to creating the shortcut but you can opt out in the
   prompt.
5. The installer automatically starts the app after setup. You can relaunch it
   later by running one of the created launchers or the desktop shortcut.

Pass `-DesktopShortcut` to the script if you want to skip the prompt and always
create the desktop entry during unattended installs.

### What the installer does

- Ensures it is running with administrative privileges so it can write to the
  chosen install path.
- Locates Python 3.10+ using `py -3`, `python`, or `python3`. If no compatible
  interpreter is found, it guides you to the official Python download.
- Builds the `dist/aegis-welcome.pyz` archive via `run_me_to_install_aegis.py`
  to keep the packaging process consistent with other platforms.
- Copies the archive into your selected directory, mirrors the freshly built
  `.venv` Python environment, and writes batch/PowerShell launchers that prefer
  that embedded interpreter (falling back to the system Python). The batch file
  is used to start the app automatically at the end of installation. If you
  allow it, the installer also drops a desktop shortcut named
  `A.E.G.I.S. Welcome` that points to the batch launcher.

### Welcome app quick links

The welcome window now includes buttons that open the operator chat and the
A.L.I.C.E. experience in your default browser. You can control where those
buttons point by setting environment variables before launching the app:

- `AEGIS_PORTAL_URL` – base URL (defaults to `http://localhost:8000`).
- `AEGIS_CHAT_URL` – full chat URL (defaults to `<AEGIS_PORTAL_URL>/chat`).
- `AEGIS_ALICE_URL` – full A.L.I.C.E. URL (defaults to
  `<AEGIS_PORTAL_URL>/alice`).

You can re-run the installer at any time; it will rebuild the archive and
overwrite the installed files without needing external packaging tools.
