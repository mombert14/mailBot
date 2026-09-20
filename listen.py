"""Bevakar inkorgen: bedömer varje nytt mail och gör det kategorin innebär.

    python listen.py            # torrläge - visar bara vad som skulle hända
    python listen.py --skarp    # slänger, avregistrerar och sparar utkast

Avsluta med Ctrl+C. Ingenting skickas någonsin automatiskt - svar hamnar
alltid som utkast i Gmail.
"""
import json
import sys
import threading
import time

from google.api_core.exceptions import DeadlineExceeded
from google.cloud import pubsub_v1
from openai import OpenAI

import act
from auth import get_credentials
from classify import ask_model, rule_verdict
from config import PROJECT_ID, SUBSCRIPTION_ID
from mail import fetch_message
from state import load_history_id, save_history_id
from watch import gmail_service, start_watch

MAX_MESSAGES = 3  # små omgångar hinner alltid behandlas inom ack-fristen
PULL_TIMEOUT = 20  # sekunder per pull-anrop innan loopen försöker igen
BODY_PREVIEW = 200  # tecken av brödtexten som visas


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


def show(mail: dict, verdict: dict) -> None:
    print(f"\n  {mail['from'][:50]}")
    print(f"  {mail['subject'][:60]}")
    print(
        f"  -> {verdict['kategori'].upper()} "
        f"({verdict['sakerhet']}, {verdict['av']})  {verdict['motivering'][:60]}"
    )

    preview = " ".join(mail["body"].split())[:BODY_PREVIEW]
    if preview:
        print(f"     {preview}...")


def handle_notification(gmail, client, data: dict, dry_run: bool) -> None:
    """En notifiering säger bara 'något hände' - historyId berättar vad."""
    since = load_history_id() or data["historyId"]
    message_ids, latest = new_message_ids(gmail, since)

    for message_id in message_ids:
        mail = fetch_message(gmail, message_id)
        verdict = rule_verdict(mail) or ask_model(client, mail)
        show(mail, verdict)

        for result in act.handle(gmail, client, mail, verdict["kategori"], dry_run):
            print(f"     · {result}")

    save_history_id(latest)


def pull_loop(subscriber, subscription_path, gmail, client, stop, dry_run) -> None:
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
            handle_notification(gmail, client, data, dry_run)
            ack_ids.append(received.ack_id)

        if ack_ids:
            subscriber.acknowledge(
                request={"subscription": subscription_path, "ack_ids": ack_ids}
            )


def main() -> None:
    dry_run = "--skarp" not in sys.argv

    creds = get_credentials()
    gmail = gmail_service(creds)
    client = OpenAI(max_retries=5)

    start_watch(gmail)
    subscriber = pubsub_v1.SubscriberClient(credentials=creds)
    subscription_path = subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_ID)

    mode = "TORRLÄGE - inget rörs i Gmail" if dry_run else "SKARPT LÄGE - slänger, avregistrerar, draftar"
    print(f"Bevakning aktiv. {mode}")
    print(f"Lyssnar på {subscription_path} (Ctrl+C för att avsluta)")

    # pull() blockerar i gRPC:s C-kod, dit Ctrl+C aldrig når. Därför körs loopen
    # i en bakgrundstråd medan huvudtråden sover - sömn går att avbryta.
    stop = threading.Event()
    worker = threading.Thread(
        target=pull_loop,
        args=(subscriber, subscription_path, gmail, client, stop, dry_run),
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
