"""Hämtar notifieringar från pull-subscriptionen och skriver ut nya mail.

Kör:  python listen.py   (avsluta med Ctrl+C)
"""
import base64
import json
import re
import threading
import time
from html import unescape

from google.api_core.exceptions import DeadlineExceeded
from google.cloud import pubsub_v1

from auth import get_credentials
from config import PROJECT_ID, SUBSCRIPTION_ID
from state import load_history_id, save_history_id
from watch import gmail_service, start_watch

MAX_MESSAGES = 10
PULL_TIMEOUT = 20  # sekunder per pull-anrop innan loopen försöker igen
BODY_PREVIEW = 600  # tecken av brödtexten som skrivs ut


def new_message_ids(gmail, since_history_id: str) -> tuple[list[str], str]:
    """Returnerar id:n för mail som lagts till i inkorgen sedan given historyId."""
    message_ids: list[str] = []
    latest = since_history_id
    page_token = None

    while True:
        response = (
            gmail.users()
            .history()
            .list(
                userId="me",
                startHistoryId=since_history_id,
                historyTypes=["messageAdded"],
                labelId="INBOX",
                pageToken=page_token,
            )
            .execute()
        )

        for entry in response.get("history", []):
            for added in entry.get("messagesAdded", []):
                message_ids.append(added["message"]["id"])

        latest = response.get("historyId", latest)
        page_token = response.get("nextPageToken")
        if not page_token:
            return message_ids, latest


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


def fetch_message(gmail, message_id: str) -> dict:
    """Hämtar hela mailet och plockar ut det vi bryr oss om."""
    message = (
        gmail.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )
    headers = {
        header["name"].lower(): header["value"]
        for header in message["payload"].get("headers", [])
    }
    return {
        "id": message_id,
        "from": headers.get("from", "?"),
        "subject": headers.get("subject", "(inget ämne)"),
        "body": extract_body(message["payload"]),
    }


def print_message(mail: dict) -> None:
    print(f"  {mail['id']}  från: {mail['from']}")
    print(f"  ämne: {mail['subject']}")

    body = mail["body"]
    if not body:
        print("    (ingen läsbar text)")
    else:
        for line in body[:BODY_PREVIEW].splitlines():
            print(f"    {line}")
        if len(body) > BODY_PREVIEW:
            print(f"    [...{len(body) - BODY_PREVIEW} tecken till]")
    print()


def handle_notification(gmail, data: dict) -> None:
    """En notifiering säger bara 'något hände' - historyId berättar vad."""
    since = load_history_id() or data["historyId"]
    message_ids, latest = new_message_ids(gmail, since)

    if message_ids:
        print(f"{len(message_ids)} nytt mail i inkorgen:")
        for message_id in message_ids:
            print_message(fetch_message(gmail, message_id))
    else:
        print("Notifiering utan nya inkorgsmail (t.ex. läst/flyttat mail).")

    save_history_id(latest)


def pull_loop(subscriber, subscription_path: str, gmail, stop: threading.Event) -> None:
    """Hämtar och behandlar notifieringar tills stop sätts."""
    while not stop.is_set():
        try:
            response = subscriber.pull(
                request={
                    "subscription": subscription_path,
                    "max_messages": MAX_MESSAGES,
                },
                timeout=PULL_TIMEOUT,
            )
        except DeadlineExceeded:
            continue  # inget nytt inom timeouten - pulla igen
        except Exception:
            if stop.is_set():
                return  # kopplingen stängdes under avslut, väntat
            raise

        ack_ids = []
        for received in response.received_messages:
            # message.data är redan avkodad bytes - Pub/Sub-klienten sköter base64.
            data = json.loads(received.message.data)
            handle_notification(gmail, data)
            ack_ids.append(received.ack_id)

        if ack_ids:
            subscriber.acknowledge(
                request={"subscription": subscription_path, "ack_ids": ack_ids}
            )


def main() -> None:
    creds = get_credentials()
    gmail = gmail_service(creds)

    start_watch(gmail)
    print("Bevakning aktiv.")

    subscriber = pubsub_v1.SubscriberClient(credentials=creds)
    subscription_path = subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_ID)
    print(f"Lyssnar på {subscription_path} (Ctrl+C för att avsluta)\n")

    # pull() blockerar i gRPC:s C-kod, dit Ctrl+C aldrig når. Därför körs loopen
    # i en bakgrundstråd medan huvudtråden sover - sömn går att avbryta.
    stop = threading.Event()
    worker = threading.Thread(
        target=pull_loop,
        args=(subscriber, subscription_path, gmail, stop),
        daemon=True,
    )
    worker.start()

    try:
        while worker.is_alive():
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\nAvslutar.")
    finally:
        stop.set()
        subscriber.close()


if __name__ == "__main__":
    main()
