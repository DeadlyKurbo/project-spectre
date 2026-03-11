# A.E.G.I.S. — Operator Chat Desktop App

**A.E.G.I.S.** (Administrative & Engagement Global Interface System) is a Discord-style desktop app for operator chat. Messages are stored locally—no server connection required.

---

## For Users: One EXE, That's It

1. **Download** `AEGIS.exe` from the [releases](../../releases) or build it (see below).
2. **Double-click** to run. No installation, no setup wizard.
3. **Configure** — Click **Settings** and set your **Display name** (the name others will see in chat).

No Python, no installer, no command line. Just one file.

---

## For Developers: Build the EXE

From the `aegis/` folder:

```bash
cd aegis
python build_installer.py
```

This produces `dist/AEGIS.exe` — a single portable file. Distribute it; users double-click to run.

---

## What the App Does

- **Discord-style interface** — Familiar chat layout with sidebar and message feed
- **Local messaging** — Messages stored securely in your app data folder
- **No server required** — Works completely offline, independent of ALICE or any portal
- **Secure storage** — Messages saved in `%APPDATA%\AEGIS` (Windows) with user-only permissions

---

## Requirements

- **Windows** (tested on Windows 10/11)
- No internet connection needed

---

## Message Storage

Messages are stored in a JSON file at:

- **Windows**: `%APPDATA%\AEGIS\chat_messages.json`
- **macOS**: `~/Library/Application Support/AEGIS/chat_messages.json`
- **Linux**: `~/.local/share/AEGIS/chat_messages.json`

The file is restricted to the current user. Older messages are pruned automatically (max 500).

---

## Advanced

- **Environment variable** (optional): `AEGIS_OPERATOR_NAME` — default display name
- **Config file**: Stored in the install folder or `~/.aegis-config.json` if not writable
