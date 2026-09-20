"""Sparar de senaste inkorgsmailen som JSON-filer, en per mail.

    python dump_corpus.py            # 200 mail
    python dump_corpus.py 50         # 50 mail

Arkivet gör att klassificeringen kan utvecklas mot samma mail om och om igen,
utan att vänta på ny post. Körs om utan risk - redan sparade mail hoppas över.
"""
import json
import sys
import time

from googleapiclient.errors import HttpError

from config import BASE_DIR
from mail import fetch_message
from watch import gmail_service

CORPUS_DIR = BASE_DIR / "corpus"
DEFAULT_COUNT = 200
PAGE_SIZE = 100  # Gmail ger max 100 id:n per anrop

PAUSE = 0.3  # sekunder mellan mail, för att hålla sig under Gmails kvot
RETRY_STATUSES = {403, 429, 500, 503}
MAX_ATTEMPTS = 5


def fetch_with_retry(gmail, message_id: str) -> dict:
    """Hämtar ett mail och backar undan om Gmail säger att vi går för fort."""
    for attempt in range(MAX_ATTEMPTS):
        try:
            return fetch_message(gmail, message_id)
        except HttpError as error:
            last_try = attempt == MAX_ATTEMPTS - 1
            if error.status_code not in RETRY_STATUSES or last_try:
                raise
            wait = 5 * 2**attempt  # 5, 10, 20, 40 sekunder
            print(f"    kvoten full - väntar {wait}s och försöker igen")
            time.sleep(wait)

    raise RuntimeError("oåtkomlig")  # för typkontrollens skull


def inbox_message_ids(gmail, count: int) -> list[str]:
    """Id:n för de senaste mailen i inkorgen, nyast först."""
    message_ids: list[str] = []
    page_token = None

    while len(message_ids) < count:
        response = (
            gmail.users()
            .messages()
            .list(
                userId="me",
                labelIds=["INBOX"],
                maxResults=min(PAGE_SIZE, count - len(message_ids)),
                pageToken=page_token,
            )
            .execute()
        )

        message_ids.extend(m["id"] for m in response.get("messages", []))

        page_token = response.get("nextPageToken")
        if not page_token:
            break

    return message_ids[:count]


def existing_state(path) -> str:
    """Uppmärkningen är handarbete - den överlever en omhämtning."""
    if not path.exists():
        return ""
    return json.loads(path.read_text(encoding="utf-8")).get("state", "")


def main() -> None:
    force = "--force" in sys.argv
    numbers = [a for a in sys.argv[1:] if not a.startswith("-")]
    count = int(numbers[0]) if numbers else DEFAULT_COUNT
    CORPUS_DIR.mkdir(exist_ok=True)

    gmail = gmail_service()
    message_ids = inbox_message_ids(gmail, count)
    print(f"Hittade {len(message_ids)} mail i inkorgen. Hämtar...\n")

    saved = skipped = 0
    for number, message_id in enumerate(message_ids, start=1):
        path = CORPUS_DIR / f"{message_id}.json"
        if path.exists() and not force:
            skipped += 1
            continue

        mail = fetch_with_retry(gmail, message_id)
        mail["state"] = existing_state(path)
        path.write_text(json.dumps(mail, ensure_ascii=False, indent=2), encoding="utf-8")
        saved += 1

        subject = mail["subject"][:60]
        print(f"  {number}/{len(message_ids)}  {subject}")
        time.sleep(PAUSE)

    print(f"\nKlart. {saved} nya, {skipped} fanns redan. Mapp: {CORPUS_DIR}")


if __name__ == "__main__":
    main()
