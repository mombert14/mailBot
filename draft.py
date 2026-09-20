"""Skriver ett utkast till svar, i samma ton som du brukar använda.

    python draft.py --korpus       # torrläge på korpusets svar-mail, skriver ut
    python draft.py <mail-id>      # ett visst mail, skriver ut
    python draft.py <mail-id> --spara   # skapar utkastet i Gmail

Utan --spara rörs ingenting i Gmail. Ett utkast skickas aldrig automatiskt.
"""
import base64
import json
import re
import sys
from email.message import EmailMessage

from openai import OpenAI

from auth import get_credentials
from config import BASE_DIR  # laddar .env, där OPENAI_API_KEY ligger
from mail import execute, fetch_message, parse_message
from watch import gmail_service

CORPUS_DIR = BASE_DIR / "corpus"
MODEL = "gpt-4o-mini"
STYLE_EXAMPLES = 3  # tidigare svar från dig som visas som stilprov
MAX_QUOTED = 3000  # tecken per meddelande i tråden

SYSTEM = """Du skriver utkast till mailsvar åt Frithjof Solterbeck.

Du får se hur han själv brukar skriva, och sedan konversationen han ska svara på.
Härma hans ton, längd och hälsningsfraser - inte en generisk artig mailton.
Skriver han kort ska du skriva kort. Använder han inte "Med vänlig hälsning"
ska du inte heller göra det.

Svara på samma språk som det inkommande mailet.

Skriv bara själva brödtexten. Ingen ämnesrad, inga citat av tidigare mail.

Utkastet är en utgångspunkt som Frithjof läser igenom och redigerar innan han
skickar - inte ett färdigt svar. Skriv det naturligt och fullständigt.

En hård regel: hitta aldrig på konkreta uppgifter. Datum, klockslag, belopp,
mailadresser, telefonnummer, länkar och namn på personer eller företag får bara
förekomma om de står i konversationen. Behöver svaret en sådan uppgift som du
inte har, skriv [...] i stället för att gissa.

I kommentaren skriver du kort vad han bör kontrollera innan han skickar. En
mening räcker. Finns inget särskilt att kontrollera skriver du "Inget särskilt."."""

SCHEMA = {
    "type": "object",
    "properties": {
        "utkast": {"type": "string"},
        "kommentar": {"type": "string"},
    },
    "required": ["utkast", "kommentar"],
    "additionalProperties": False,
}

# Mönster som inleder citerad historik - allt därefter är gammalt.
QUOTE_STARTS = (
    re.compile(r"^\s*>", re.MULTILINE),
    re.compile(r"^\s*On .+ wrote:", re.MULTILINE),
    re.compile(r"^\s*Den .+ skrev .+:", re.MULTILINE),
    re.compile(r"^.*[-_]{2,}\s*Original Message", re.MULTILINE),
    # Outlook: From:/Från: följt av Sent:/Skickat: någon rad ned
    re.compile(r"^(From|Från):[^\n]*\n(?:[^\n]*\n){0,3}?\s*(Sent|Skickat):", re.MULTILINE),
)


def strip_quotes(body: str) -> str:
    """Behåller bara det som är nytt i meddelandet."""
    cuts = [m.start() for m in (p.search(body) for p in QUOTE_STARTS) if m]
    if cuts:
        kept = body[: min(cuts)]
        # Ligger citatet först skulle allt försvinna - ta bort raderna i stället.
        if kept.strip():
            body = kept
        else:
            body = "\n".join(l for l in body.splitlines() if not l.lstrip().startswith(">"))

    body = re.sub(r"^--\s*$.*", "", body, flags=re.MULTILINE | re.DOTALL)  # signatur
    body = re.sub(r"https?://\S+", " ", body)
    return re.sub(r"\n\s*\n\s*\n+", "\n\n", body).strip()


def address_of(header: str) -> str:
    match = re.search(r"<([^>]+)>", header) or re.search(r"(\S+@\S+)", header)
    return match.group(1).lower() if match else header.lower()


def thread_messages(gmail, thread_id: str) -> list[dict]:
    """Alla meddelanden i tråden, äldst först, utan citat.

    threads.get ger hela meddelandena direkt - inga extra anrop behövs.
    """
    thread = execute(gmail.users().threads().get(userId="me", id=thread_id, format="full"))

    messages = []
    for raw in thread.get("messages", []):
        mail = parse_message(raw)
        mail["body"] = strip_quotes(mail["body"])[:MAX_QUOTED]
        messages.append(mail)
    return messages


def style_examples(gmail, address: str) -> list[str]:
    """Dina egna tidigare svar till samma person - bästa källan till din ton."""
    response = execute(
        gmail.users()
        .messages()
        .list(userId="me", q=f"from:me to:{address}", maxResults=STYLE_EXAMPLES)
    )

    examples = []
    for hit in response.get("messages", []):
        body = strip_quotes(fetch_message(gmail, hit["id"])["body"])
        if body:
            examples.append(body[:1500])
    return examples


def build_prompt(thread: list[dict], examples: list[str]) -> str:
    parts = []

    if examples:
        parts.append("SÅ HÄR BRUKAR FRITHJOF SKRIVA TILL DEN HÄR PERSONEN:\n")
        for example in examples:
            parts.append(f"---\n{example}\n")
    else:
        parts.append("(Inga tidigare svar till den här personen - håll en neutral ton.)\n")

    parts.append("\nKONVERSATIONEN:\n")
    for message in thread:
        parts.append(f"--- {message['from']} ({message['date']})\n{message['body']}\n")

    parts.append("\nSkriv ett utkast till svar på det sista meddelandet.")
    return "\n".join(parts)


def write_draft(client: OpenAI, prompt: str) -> dict:
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=2000,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": prompt},
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "utkast", "strict": True, "schema": SCHEMA},
        },
    )
    choice = response.choices[0]

    if choice.message.refusal:
        raise SystemExit("Modellen avböjde att skriva ett svar på det här mailet.")

    return json.loads(choice.message.content)


def save_to_gmail(gmail, original: dict, body: str) -> str:
    """Skapar utkastet i Gmail, inuti rätt tråd."""
    message = EmailMessage()
    message["To"] = original["from"]
    subject = original["subject"]
    message["Subject"] = subject if subject.lower().startswith("re:") else f"Re: {subject}"

    # Utan dessa två hamnar svaret bredvid tråden i stället för i den.
    if original["message_id_header"]:
        message["In-Reply-To"] = original["message_id_header"]
        references = f"{original['references']} {original['message_id_header']}".strip()
        message["References"] = references

    message.set_content(body)
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    draft = (
        gmail.users()
        .drafts()
        .create(userId="me", body={"message": {"raw": raw, "threadId": original["thread_id"]}})
        .execute()
    )
    return draft["id"]


def show(original: dict, result: dict) -> None:
    print("\n" + "═" * 70)
    print(f"SVAR TILL : {original['from']}")
    print(f"ÄMNE      : {original['subject']}")
    print("═" * 70)
    print(result["utkast"])
    print("─" * 70)
    print(f"Kommentar: {result['kommentar']}")


def handle(gmail, client, message_id: str, save: bool) -> None:
    original = fetch_message(gmail, message_id)
    thread = thread_messages(gmail, original["thread_id"])
    examples = style_examples(gmail, address_of(original["from"]))

    result = write_draft(client, build_prompt(thread, examples))
    show(original, result)

    print(f"({len(thread)} meddelanden i tråden, {len(examples)} stilprov)")
    if save:
        draft_id = save_to_gmail(gmail, original, result["utkast"])
        print(f"Sparat som utkast i Gmail: {draft_id}")


def corpus_ids() -> list[str]:
    """Mail du märkt som 'svar', ett per tråd.

    Flera mail ur samma konversation ger nästan identiska utkast - det är
    bara det sista i tråden man svarar på.
    """
    senaste: dict[str, dict] = {}
    for path in sorted(CORPUS_DIR.glob("*.json")):
        mail = json.loads(path.read_text(encoding="utf-8"))
        if mail["state"] != "svar":
            continue
        tidigare = senaste.get(mail["thread_id"])
        if tidigare is None or mail["date"] > tidigare["date"]:
            senaste[mail["thread_id"]] = mail

    return [mail["id"] for mail in senaste.values()]


def main() -> None:
    save = "--spara" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]

    creds = get_credentials()
    gmail = gmail_service(creds)
    client = OpenAI(max_retries=5)

    if "--korpus" in sys.argv:
        ids = corpus_ids()
        print(f"{len(ids)} mail märkta som 'svar' i korpuset. Torrkörning.\n")
        for message_id in ids:
            handle(gmail, client, message_id, save=False)
        return

    if not args:
        raise SystemExit(__doc__)

    handle(gmail, client, args[0], save)


if __name__ == "__main__":
    main()
