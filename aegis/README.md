# A.E.G.I.S. — Operator Chat Desktop App

**A.E.G.I.S.** (Administrative & Engagement Global Interface System) is a lightweight desktop app that connects you to your community's **ALICE chatroom** — no browser required.

---

## What it does

- Connects directly to your community's chat relay
- Lets you read and send messages from a terminal-style window
- No password needed — just enter your username and you're in

---

## Quick start (Windows)

1. **Install** — Double-click `Install-AEGIS.bat` and follow the prompts.
2. **Launch** — Double-click `Launch-AEGIS.bat`.
3. **Configure** — Click **Settings** and set:
   - **Portal base** — Your community's website URL (e.g. `https://yoursite.railway.app`)
   - **Display name** — The name others will see in chat
4. **Chat** — The app connects automatically. Type your message and press Enter.

---

## Requirements

- **Windows** (tested on Windows 10/11)
- Internet connection
- Your community must be running the Project Spectre portal with ALICE chat enabled

---

## First-time setup

| Step | What to do |
|------|------------|
| Portal URL | In Settings, enter your community's full URL. Use **Test connection** to verify. |
| Username | Enter the name you want to use in chat. No password or account setup required. |

---

## Troubleshooting

| Problem | Solution |
|--------|----------|
| "Cannot reach the portal" | Check your Portal URL in Settings. Make sure your community site is online. |
| "Access denied" | Your community may restrict chat access. Contact an admin. |
| App won't start | Run `Install-AEGIS.bat` first. If Python fails, install Python 3.11 from [python.org](https://python.org). |

---

## Advanced

- **Environment variables** (optional): `AEGIS_PORTAL_URL`, `AEGIS_OPERATOR_NAME`
- **Manual launch**: `.venv\Scripts\python.exe dist\aegis-welcome.pyz`
- **Build from source**: Run `python build_aegis_zipapp.py` from this folder
