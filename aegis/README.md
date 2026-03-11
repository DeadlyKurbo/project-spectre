# A.E.G.I.S. — Operator Chat Desktop App

**A.E.G.I.S.** (Administrative & Engagement Global Interface System) is a lightweight desktop app that connects you to your community's **ALICE chatroom** — no browser required.

---

## For Users: Easy Install

1. **Download** `AEGIS-Setup.exe` from the [releases](../../releases) or build it (see below).
2. **Run** the installer — double-click and follow the prompts.
3. **Launch** A.E.G.I.S. from the Desktop or Start Menu shortcut.
4. **Configure** — Click **Settings** and set:
   - **Portal base** — Your community's website URL (e.g. `https://yoursite.railway.app`)
   - **Display name** — The name others will see in chat

No Python or command line needed. The installer puts everything in place and creates shortcuts.

---

## For Developers: Build the Installer

From the `aegis/` folder:

```bash
cd aegis
python build_installer.py
```

This produces:

- `dist/AEGIS.exe` — Standalone launcher (no Python required)
- `dist/AEGIS-Setup.exe` — Installer to distribute to users

Distribute `AEGIS-Setup.exe` — users double-click to install.

---

## What the App Does

- Connects directly to your community's chat relay
- Lets you read and send messages from a terminal-style window
- No password needed — just enter your username and you're in

---

## Requirements

- **Windows** (tested on Windows 10/11)
- Internet connection
- Your community must be running the Project Spectre portal with ALICE chat enabled

---

## Troubleshooting

| Problem | Solution |
|--------|----------|
| "Cannot reach the portal" | Check your Portal URL in Settings. Make sure your community site is online. |
| "Access denied" | Your community may restrict chat access. Contact an admin. |
| Installer won't run | Right-click → Run as administrator if you see permission errors. |

---

## Advanced

- **Environment variables** (optional): `AEGIS_PORTAL_URL`, `AEGIS_OPERATOR_NAME`
- **Config file**: Stored in the install folder or `~/.aegis-config.json` if not writable
