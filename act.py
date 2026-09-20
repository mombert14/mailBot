"""Vad som händer med ett mail när det har bedömts.

    brus     -> papperskorgen, och avregistrering om det går
    läsvärt  -> ingenting, ligger kvar i inkorgen
    svar     -> ett utkast skapas i tråden

Torrläge är standard. Ingenting i Gmail rörs om inte skarpt läge begärs
uttryckligen, och ingenting skickas någonsin utan att du tryckt på knappen.
"""
import re
import urllib.error
import urllib.request
from email.message import EmailMessage

from config import BASE_DIR
from draft import build_prompt, save_to_gmail, style_examples, thread_messages, write_draft
from draft import address_of
from mail import execute

ALLOWLIST_FILE = BASE_DIR / "never_unsubscribe.txt"
HTTP_TIMEOUT = 15


def never_unsubscribe() -> list[str]:
    """Avsändare som får slängas men aldrig avregistreras."""
    if not ALLOWLIST_FILE.exists():
        return []
    return [
        line.strip().lower()
        for line in ALLOWLIST_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def unsubscribe_targets(header: str) -> tuple[str | None, str | None]:
    """Plockar ut https- och mailto-adress ur List-Unsubscribe."""
    https = re.search(r"<(https://[^>]+)>", header or "")
    mailto = re.search(r"<mailto:([^>]+)>", header or "")
    return (https.group(1) if https else None, mailto.group(1) if mailto else None)


def unsubscribe(gmail, mail: dict, dry_run: bool) -> str:
    """Försöker avregistrera. Returnerar vad som gjordes, eller varför inte."""
    if not mail["list_unsubscribe"]:
        return "ingen avregistreringslänk"

    sender = mail["from"].lower()
    for protected in never_unsubscribe():
        if protected in sender:
            return f"skyddad avsändare ({protected})"

    url, mailto = unsubscribe_targets(mail["list_unsubscribe"])

    # Ett enda anrop räcker bara när avsändaren stödjer det (RFC 8058).
    if url and mail.get("one_click"):
        if dry_run:
            return f"skulle avregistrera via {url[:50]}"
        request = urllib.request.Request(
            url, data=b"List-Unsubscribe=One-Click", method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT) as response:
                return f"avregistrerad ({response.status})"
        except (urllib.error.URLError, OSError) as error:
            return f"avregistrering misslyckades: {error}"

    if mailto:
        if dry_run:
            return f"skulle mejla {mailto}"
        message = EmailMessage()
        message["To"] = mailto
        message["Subject"] = "unsubscribe"
        message.set_content("unsubscribe")
        import base64

        raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
        execute(gmail.users().messages().send(userId="me", body={"raw": raw}))
        return f"avregistrering mejlad till {mailto}"

    if url:
        return f"kräver manuellt klick: {url[:60]}"
    return "kunde inte tolka avregistreringslänken"


def trash(gmail, mail: dict, dry_run: bool) -> str:
    if dry_run:
        return "skulle slängas"
    execute(gmail.users().messages().trash(userId="me", id=mail["id"]))
    return "slängd"


def make_draft(gmail, client, mail: dict, dry_run: bool) -> str:
    thread = thread_messages(gmail, mail["thread_id"])
    examples = style_examples(gmail, address_of(mail["from"]))
    result = write_draft(client, build_prompt(thread, examples))

    print("    " + "\n    ".join(result["utkast"].splitlines()))
    print(f"    ({result['kommentar']})")

    if dry_run:
        return "skulle sparas som utkast"
    draft_id = save_to_gmail(gmail, mail, result["utkast"])
    return f"utkast sparat ({draft_id})"


def handle(gmail, client, mail: dict, category: str, dry_run: bool = True) -> list[str]:
    """Utför det kategorin innebär. Returnerar en rad per åtgärd."""
    if category == "brus":
        return [trash(gmail, mail, dry_run), unsubscribe(gmail, mail, dry_run)]

    if category == "svar":
        return [make_draft(gmail, client, mail, dry_run)]

    return ["lämnas i inkorgen"]
