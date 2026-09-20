"""Hämtar ett mail från Gmail och gör om det till en enkel, platt post.

Används både av listen.py (ett mail i taget) och dump_corpus.py (många).
"""
import base64
import re
from html import unescape

# Headers vi bryr oss om, i gemener eftersom Gmail varierar skrivsättet.
WANTED_HEADERS = ("from", "to", "subject", "date", "list-unsubscribe")


def decode_part(data: str) -> str:
    """Gmail kodar brödtexten som base64url, ibland utan padding."""
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def html_to_text(html: str) -> str:
    """Grov nedplockning av HTML till läsbar text."""
    text = re.sub(r"(?is)<(script|style).*?</\1>", " ", html)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return unescape(text).replace("\xa0", " ")  # &nbsp; -> vanligt blanksteg


def collect_parts(part: dict, found: dict) -> None:
    """Går igenom MIME-trädet och sparar första text-delen av varje sort.

    Bilagor saknar 'data' (de har ett attachmentId istället) och hoppas över.
    """
    mime = part.get("mimeType", "")
    data = part.get("body", {}).get("data")
    if data and mime in ("text/plain", "text/html") and mime not in found:
        found[mime] = decode_part(data)

    for sub_part in part.get("parts", []):
        collect_parts(sub_part, found)


def extract_body(payload: dict) -> str:
    """Brödtexten som ren text. Föredrar text/plain, faller tillbaka på HTML."""
    found: dict[str, str] = {}
    collect_parts(payload, found)

    if "text/plain" in found:
        text = found["text/plain"]
    elif "text/html" in found:
        text = html_to_text(found["text/html"])
    else:
        return ""

    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", text).strip()


def extract_attachments(part: dict, found: list) -> None:
    """Namn och storlek på bilagor - aldrig innehållet."""
    body = part.get("body", {})
    if part.get("filename") and body.get("attachmentId"):
        found.append({"filename": part["filename"], "size": body.get("size", 0)})

    for sub_part in part.get("parts", []):
        extract_attachments(sub_part, found)


def fetch_message(gmail, message_id: str) -> dict:
    """Hämtar hela mailet och plockar ut det vi bryr oss om."""
    message = (
        gmail.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )
    payload = message["payload"]

    headers = {
        header["name"].lower(): header["value"]
        for header in payload.get("headers", [])
        if header["name"].lower() in WANTED_HEADERS
    }

    attachments: list[dict] = []
    extract_attachments(payload, attachments)

    return {
        "id": message_id,
        "thread_id": message.get("threadId", ""),
        "date": headers.get("date", ""),
        "from": headers.get("from", "?"),
        "to": headers.get("to", ""),
        "subject": headers.get("subject", "(inget ämne)"),
        "labels": message.get("labelIds", []),
        "list_unsubscribe": headers.get("list-unsubscribe"),
        "attachments": attachments,
        "body": extract_body(payload),
        "state": "",  # fylls i för hand: brus | läsvärt | svar
    }
