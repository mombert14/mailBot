"""Startar Gmail-bevakning som publicerar till Pub/Sub-topicen.

Gmail slutar skicka efter 7 dagar - kör om detta minst en gång i veckan.
"""
from datetime import datetime, timezone

from googleapiclient.discovery import build

from auth import get_credentials
from config import TOPIC_PATH
from state import load_history_id, save_history_id


def gmail_service(creds=None):
    return build("gmail", "v1", credentials=creds or get_credentials())


def start_watch(gmail=None) -> dict:
    gmail = gmail or gmail_service()
    response = (
        gmail.users()
        .watch(
            userId="me",
            body={
                "topicName": TOPIC_PATH,
                "labelIds": ["INBOX"],
                "labelFilterBehavior": "include",
            },
        )
        .execute()
    )

    # Första gången: börja lyssna från och med nuet.
    if load_history_id() is None:
        save_history_id(response["historyId"])

    return response


def main() -> None:
    response = start_watch()
    expires = datetime.fromtimestamp(
        int(response["expiration"]) / 1000, tz=timezone.utc
    )
    print(f"Bevakning startad. historyId={response['historyId']}")
    print(f"Giltig till: {expires:%Y-%m-%d %H:%M} UTC")
    print("\nNästa steg: python listen.py")


if __name__ == "__main__":
    main()
