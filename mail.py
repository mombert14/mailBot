"""Hämtar ett mail från Gmail och gör om det till en enkel, platt post.

Används både av listen.py (ett mail i taget) och dump_corpus.py (många).
"""
import base64
import re
import time
from html import unescape

from googleapiclient.errors import HttpError

RETRY_STATUSES = {403, 429, 500, 503}
MAX_ATTEMPTS = 5

# Headers vi bryr oss om, i gemener eftersom Gmail varierar skrivsättet.
WANTED_HEADERS = (
    "from", "to", "subject", "date", "list-unsubscribe",
    "list-unsubscribe-post",  # finns den kan avregistrering ske med ett anrop
    "message-id", "references",  # behövs för att ett svar ska hamna i rätt tråd
)


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


def execute(request):
    """Kör ett Gmail-anrop och backar undan om kvoten är full."""
    for attempt in range(MAX_ATTEMPTS):
        try:
            return request.execute()
        except HttpError as error:
            if error.status_code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS - 1:
                raise
            wait = 5 * 2**attempt  # 5, 10, 20, 40 sekunder
            print(f"    kvoten full - väntar {wait}s och försöker igen")
            time.sleep(wait)


def parse_message(message: dict) -> dict:
    """Gör om Gmails svar till vår platta post. Inga API-anrop."""
    payload = message["payload"]
    message_id = message["id"]

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
        "one_click": "one-click" in headers.get("list-unsubscribe-post", "").lower(),
        "message_id_header": headers.get("message-id", ""),
        "references": headers.get("references", ""),
        "attachments": attachments,
        "body": extract_body(payload),
        "state": "",  # fylls i för hand: brus | läsvärt | svar
    }


def fetch_message(gmail, message_id: str) -> dict:
    """Hämtar ett mail och plockar ut det vi bryr oss om."""
    request = gmail.users().messages().get(userId="me", id=message_id, format="full")
    return parse_message(execute(request))
