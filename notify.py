"""Skickar en notis till Discord för varje beslut boten fattar.

Rubriken är avsändarens adress, kroppen är vad boten gjorde. Saknas
DISCORD_WEBHOOK i .env görs ingenting alls - funktionen är frivillig.

Discord får aldrig fälla boten: en trasig webhook loggas och ignoreras.
"""
import json
import re
import urllib.error
import urllib.request

from config import DISCORD_WEBHOOK

TIMEOUT = 10

# Vilka kategorier som ska ge en notis. Ta bort "brus" om det blir för mycket.
NOTIFY_ABOUT = ("brus", "läsvärt", "svar")

COLORS = {
    "brus": 0x95A5A6,  # grå
    "läsvärt": 0x3498DB,  # blå
    "svar": 0x2ECC71,  # grön
}


def sender_address(header: str) -> str:
    """Bara adressen ur 'Namn <adress>'."""
    match = re.search(r"<([^>]+)>", header) or re.search(r"(\S+@\S+)", header)
    return match.group(1) if match else header


def send(mail: dict, verdict: dict, actions: list[str]) -> None:
    """Postar en notis. Tyst om webhook saknas eller kategorin inte ska notifieras."""
    if not DISCORD_WEBHOOK or verdict["kategori"] not in NOTIFY_ABOUT:
        return

    body = "\n".join(f"• {action}" for action in actions)
    payload = {
        "embeds": [
            {
                "title": sender_address(mail["from"])[:250],
                "description": body[:4000],
                "color": COLORS.get(verdict["kategori"], 0x95A5A6),
                "fields": [
                    {"name": "Ämne", "value": (mail["subject"] or "-")[:1000]},
                    {
                        "name": "Bedömning",
                        "value": f"{verdict['kategori']} "
                                 f"({verdict['sakerhet']}, {verdict['av']})",
                    },
                ],
            }
        ]
    }

    request = urllib.request.Request(
        DISCORD_WEBHOOK,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            # Utan en riktig User-Agent svarar Discords Cloudflare med 403.
            "User-Agent": "MailBot (https://github.com/mombert14/mailBot, 1.0)",
        },
        method="POST",
    )
    try:
        urllib.request.urlopen(request, timeout=TIMEOUT)
    except (urllib.error.URLError, OSError) as error:
        print(f"     (discord-notis misslyckades: {error})")
