#!/usr/bin/env python3
"""
Diagnose script voor Project SPECTRE bot offline issues.
- Checkt env (DISCORD_TOKEN / DISCORD_BOT_TOKEN)
- Verifieert Nextcord versie (>= 2.6.0)
- Toont welk token bron wordt gebruikt
- Valideert tokenvorm (lengte/prefix) zonder token te loggen
- Simuleert bot-intents en meldt welke privileged intents vereist zijn
- Controleert Procfile-aanpak (aanwezig + verwachte inhoud)
- Geeft concrete fix-adviezen
"""

from __future__ import annotations
import os
import sys
import re
import importlib
from pathlib import Path

EXIT_FAIL = 1
EXIT_OK = 0

def info(msg: str): print(f"[INFO] {msg}")
def warn(msg: str): print(f"[WARN] {msg}")
def err(msg: str):  print(f"[ERR ] {msg}")

def check_env_tokens() -> dict:
    d = {}
    disc = os.getenv("DISCORD_TOKEN", "").strip()
    disc_old = os.getenv("DISCORD_BOT_TOKEN", "").strip()

    if disc:
        d["token_source"] = "DISCORD_TOKEN"
        d["token"] = disc
    elif disc_old:
        d["token_source"] = "DISCORD_BOT_TOKEN (fallback — update naar DISCORD_TOKEN a.u.b.)"
        d["token"] = disc_old
    else:
        d["token_source"] = None
        d["token"] = ""

    return d

def token_shape_ok(token: str) -> tuple[bool, list[str]]:
    tips = []
    if not token:
        return False, ["Geen token gevonden. Zet een geldige waarde in DISCORD_TOKEN."]
    # Discord bot tokens variëren, maar simpele sanity checks:
    if len(token) < 50:
        tips.append("Token lijkt te kort. Kopieer exact uit de Developer Portal (Reset Token indien nodig).")
    # Vroege tokens hadden soms puntjes; niet hard valideren, enkel hint geven.
    if token.count(".") != 2:
        tips.append("Token heeft geen standaard 3-delige vorm (xxx.yyy.zzz). Dit kán oké zijn, maar dubbelcheck.")
    return (len(tips) == 0), tips

def check_nextcord():
    try:
        nx = importlib.import_module("nextcord")
        ver = getattr(nx, "__version__", "unknown")
        info(f"Nextcord versie: {ver}")
        # Vergelijken op simpele manier
        def parse(v: str):
            return tuple(int(x) for x in re.findall(r"\d+", v)[:3] or [0])
        if parse(ver) < (2, 6, 0):
            warn("Nextcord < 2.6.0 gedetecteerd. Update requirements en redeploy.")
            return False
        return True
    except Exception as e:
        err(f"Kon 'nextcord' niet importeren: {e}")
        warn("Installeer dependencies opnieuw: pip install -r requirements.txt")
        return False

def check_intents_note():
    info("Benodigde privileged intents volgens code: MEMBERS + MESSAGE CONTENT.")
    print("- Ga naar https://discord.com/developers/applications → jouw app → Bot → Privileged Gateway Intents")
    print("  * Server Members: AAN")
    print("  * Message Content: AAN")
    print("Als deze uit staan: bot logt wel/niet in, maar 'ziet' weinig en lijkt 'offline' qua gedrag.")

def check_procfile():
    pf = Path("Procfile")
    expected = 'web: sh -c "python3 main.py & python3 -m uvicorn config_app:app --host 0.0.0.0 --port ${PORT:-8000}"'
    if not pf.exists():
        warn("Procfile ontbreekt. Maak een Procfile met onderstaande regel.")
        print(expected)
        return False
    content = pf.read_text(encoding="utf-8", errors="ignore").strip()
    if expected not in content:
        warn("Procfile gevonden maar lijkt af te wijken van de verwachte startregel.")
        print("Huidige inhoud:")
        print(content)
        print("\nVerwacht (of gelijkwaardig):")
        print(expected)
        return False
    info("Procfile ziet er goed uit.")
    return True

def main():
    print("=== SPECTRE Bot Offline Diagnose ===")
    ok = True

    # ENV tokens
    env = check_env_tokens()
    src = env["token_source"]
    token = env["token"]
    if not src:
        err("Geen DISCORD_TOKEN of DISCORD_BOT_TOKEN gevonden.")
        print("FIX: Zet je bot token als DISCORD_TOKEN in je Railway/host env vars.")
        ok = False
    else:
        info(f"Token bron: {src}")
        good_shape, tips = token_shape_ok(token)
        if not good_shape:
            warn("Token ziet er verdacht uit.")
            for t in tips:
                print(f"- {t}")
            ok = False
        else:
            info("Tokenvorm lijkt oké (geen garantie, maar plausibel).")

    # Nextcord versie
    if not check_nextcord():
        ok = False

    # Intents uitleg
    check_intents_note()

    # Procfile
    if not check_procfile():
        ok = False

    # Samenvatting / acties
    print("\n=== Actiepunten ===")
    if not src:
        print("- [CRIT] Zet DISCORD_TOKEN (waarde uit Developer Portal → Bot → Reset Token → kopiëren).")
    if src and "fallback" in src:
        print("- [HIGH] Je gebruikt DISCORD_BOT_TOKEN fallback. Kopieer dezelfde waarde naar DISCORD_TOKEN.")
    if not token:
        print("- [CRIT] Er is geen token waarde. Zonder token start de bot niet.")
    else:
        print("- [OK] Token ingesteld (vorm plausibel).")
    print("- [HIGH] Controleer en zet Privileged Intents aan (Members + Message Content).")
    print("- [OK/HIGH] Procfile conform? Zo niet: herstel naar de standaardregel hierboven.")
    print("- [TIP] Redeploy na env-wijzigingen zodat dependencies + runtime schoon starten.")

    if ok:
        print("\n✅ Diagnose geslaagd: configuratie lijkt in orde. Als de bot nog offline is:")
        print("   - Check logs voor 'LoginFailure' (fout token) of rate limits.")
        print("   - Reset token in Developer Portal en update DISCORD_TOKEN opnieuw.")
        print("   - Verwijder oude/duplicaat env variabelen die kunnen conflicteren.")
        return EXIT_OK
    else:
        print("\n❌ Er zijn problemen gevonden. Los de actiepunten op en redeploy.")
        return EXIT_FAIL

if __name__ == "__main__":
    sys.exit(main())
