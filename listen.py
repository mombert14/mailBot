"""Bevakar inkorgen: bedömer varje nytt mail och gör det kategorin innebär.

    python listen.py                     # torrläge - visar bara vad som skulle hända
    python listen.py --utkast            # + draftar svar (ofarligt, kan raderas)
    python listen.py --utkast --sopa     # + slänger brus (går att ta tillbaka)
    python listen.py --skarp             # allt, inklusive avregistrering

Åtgärderna slås på var för sig så att den ofarligaste kan gå skarp först.
--skarp är en genväg för --utkast --sopa --avreg.

Avsluta med Ctrl+C. Ingenting skickas någonsin automatiskt - svar hamnar
alltid som utkast i Gmail.
"""
import json
import sys
import threading
import time
from datetime import datetime

from google.api_core.exceptions import DeadlineExceeded
from google.cloud import pubsub_v1
from openai import OpenAI

from googleapiclient.errors import HttpError

import act
import logbook
import notify
from auth import get_credentials
from classify import ask_model, rule_verdict
from config import PROJECT_ID, SUBSCRIPTION_ID
from mail import fetch_message
from state import load_history_id, save_history_id
from watch import gmail_service, start_watch

MAX_MESSAGES = 3  # små omgångar hinner alltid behandlas inom ack-fristen
PULL_TIMEOUT = 20  # sekunder per pull-anrop innan loopen försöker igen
BODY_PREVIEW = 200  # tecken av brödtexten som visas
RENEW_AFTER = 24 * 3600  # Gmails bevakning dör efter 7 dagar - förnya dagligen
RETRY_PAUSE = 30  # sekunder att vänta efter ett nätverksfel innan nytt försök


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


def enabled_actions(argv: list[str]) -> set[str]:
    """Vilka åtgärder som är påslagna. Tom mängd = torrläge."""
    if "--skarp" in argv:
        return set(act.ACTIONS)
    return {name for name in act.ACTIONS if f"--{name}" in argv}


def handle_notification(gmail, client, data: dict, allowed: set[str]) -> None:
    """En notifiering säger bara 'något hände' - historyId berättar vad."""
    since = load_history_id() or data["historyId"]

    try:
        message_ids, latest = new_message_ids(gmail, since)
    except HttpError as error:
        if error.status_code != 404:
            raise
        # Gmail sparar historik i ungefär en vecka. Har programmet legat nere
        # längre än så finns vår position inte kvar - börja om från nuet.
        print("  (historiken är för gammal - börjar om från och med nu)")
        save_history_id(data["historyId"])
        return

    for message_id in message_ids:
        mail = fetch_message(gmail, message_id)
        verdict = rule_verdict(mail) or ask_model(client, mail)
        show(mail, verdict)

        results = act.handle(gmail, client, mail, verdict, allowed)
        for result in results:
            print(f"     · {result}")

        logbook.record(mail, verdict, results, allowed)
        notify.send(mail, verdict, results)

    save_history_id(latest)


def problem(what: str, error: Exception) -> None:
    """Ett fel som inte får fälla boten - skriv ner det och gå vidare."""
    print(f"  ({datetime.now():%Y-%m-%d %H:%M}  {what}: "
          f"{type(error).__name__}: {error})")


def pull_loop(subscriber, subscription_path, gmail, client, stop, allowed) -> None:
    """Hämtar och behandlar notifieringar tills stop sätts.

    Inget enskilt fel får avsluta loopen. Ett trasigt nätverk, en API-krångel
    eller ett mail som inte går att tolka ska kosta en notifiering, inte driften.
    """
    renewed = time.time()

    while not stop.is_set():
        # Utan detta slutar Gmail skicka notiser efter sju dagar, tyst.
        if time.time() - renewed > RENEW_AFTER:
            try:
                start_watch(gmail)
                renewed = time.time()
                print(f"  ({datetime.now():%Y-%m-%d %H:%M}  bevakningen förnyad)")
            except Exception as error:
                problem("kunde inte förnya bevakningen", error)
                renewed = time.time() - RENEW_AFTER + RETRY_PAUSE  # försök snart igen

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
        except Exception as error:
            if stop.is_set():
                return  # kopplingen stängdes under avslut, väntat
            problem("hämtningen misslyckades", error)
            stop.wait(RETRY_PAUSE)
            continue

        ack_ids = []
        for received in response.received_messages:
            try:
                # message.data är redan avkodad bytes - klienten sköter base64.
                data = json.loads(received.message.data)
                handle_notification(gmail, client, data, allowed)
                ack_ids.append(received.ack_id)
            except Exception as error:
                # Ingen ack - Pub/Sub levererar notifieringen igen om en stund.
                problem("kunde inte behandla notifieringen", error)

        if ack_ids:
            try:
                subscriber.acknowledge(
                    request={"subscription": subscription_path, "ack_ids": ack_ids}
                )
            except Exception as error:
                problem("ack misslyckades", error)


def main() -> None:
    allowed = enabled_actions(sys.argv)

    creds = get_credentials()
    gmail = gmail_service(creds)
    client = OpenAI(max_retries=5)

    # Börja alltid från nuet - mail som kom medan boten låg nere rörs inte.
    watch = start_watch(gmail)
    save_history_id(watch["historyId"])
    subscriber = pubsub_v1.SubscriberClient(credentials=creds)
    subscription_path = subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_ID)

    if allowed:
        vad = {"utkast": "draftar svar", "sopa": "slänger brus",
               "avreg": "avregistrerar"}
        aktiva = ", ".join(vad[name] for name in act.ACTIONS if name in allowed)
        print(f"Bevakning aktiv. SKARPT: {aktiva}")
    else:
        print("Bevakning aktiv. TORRLÄGE - inget rörs i Gmail")

    print(f"Agerar bara vid säkerhet: {', '.join(act.ACT_ON)}")
    print(f"Lyssnar på {subscription_path} (Ctrl+C för att avsluta)")

    # pull() blockerar i gRPC:s C-kod, dit Ctrl+C aldrig når. Därför körs loopen
    # i en bakgrundstråd medan huvudtråden sover - sömn går att avbryta.
    stop = threading.Event()
    worker = threading.Thread(
        target=pull_loop,
        args=(subscriber, subscription_path, gmail, client, stop, allowed),
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
