"""Klassificerar korpuset: regel först, Claude för resten.

    python classify.py            # klassificera allt som saknar bedömning
    python classify.py --om       # gör om även det som redan bedömts
    python classify.py --rapport  # bara jämförelsen mot din uppmärkning

Bedömningen skrivs som "predicted" i mailets fil. Din egen "state" rörs aldrig.
"""
import json
import re
import sys
from pathlib import Path

import anthropic

from config import BASE_DIR

CORPUS_DIR = BASE_DIR / "corpus"
MODEL = "claude-opus-5"
MAX_BODY = 2000  # tecken av brödtexten som skickas med
KATEGORIER = ("brus", "läsvärt", "svar")

SYSTEM = """Du sorterar Frithjofs inkommande mail i fyra kategorier.

brus     - massutskick: reklam, nyhetsbrev, kampanjer, notiser från sociala
           medier, "du kanske också gillar". Inget han bett om personligen.

läsvärt  - automatiskt men personligt relevant: kvitton, fakturor,
           lönespecifikationer, e-signering, verifieringskoder, boknings- och
           betalningsbekräftelser. Innehåller information som rör just honom,
           men kräver inget svar.

svar     - skrivet av en människa till honom personligen och förväntar sig ett
           svar. Typiskt rekrytering, kollegor, myndighetskontakt. Ofta del av
           en tråd (Re:, Sv:, FW:) och nästan aldrig från en noreply-adress.

Oklart   - Anser du att det är svårt att bedöma vad mailet är så skall du hanterad
det som ett läsvärt mail. 

Gränsfall: ett automatiskt mail som kräver en handling av honom (signera,
betala, boka om) är läsvärt, inte svar - han svarar inte på avsändaren.
Ett massutskick från en riktig person är ändå brus.

Svara med kategori, hur säker du är, och en kort motivering på svenska."""

SCHEMA = {
    "type": "object",
    "properties": {
        "kategori": {"type": "string", "enum": list(KATEGORIER)},
        "sakerhet": {"type": "string", "enum": ["hög", "medel", "låg"]},
        "motivering": {"type": "string"},
    },
    "required": ["kategori", "sakerhet", "motivering"],
    "additionalProperties": False,
}


def rule_verdict(mail: dict) -> dict | None:
    """Massutskick avgörs utan modell. 126 av 200 i korpuset, noll fel."""
    if mail["list_unsubscribe"]:
        return {
            "kategori": "brus",
            "sakerhet": "hög",
            "motivering": "Har List-Unsubscribe - massutskick.",
            "av": "regel",
        }
    return None


def summarize(mail: dict) -> str:
    """Det modellen får se. Tracking-länkar bort, brödtexten kortad."""
    body = re.sub(r"https?://\S+", " ", mail["body"])
    body = re.sub(r"[ \t]+", " ", body).strip()

    category = next(
        (l.replace("CATEGORY_", "") for l in mail["labels"] if l.startswith("CATEGORY_")),
        "-",
    )
    return (
        f"Från: {mail['from']}\n"
        f"Ämne: {mail['subject']}\n"
        f"Datum: {mail['date']}\n"
        f"Gmail-kategori: {category}\n"
        f"Bilagor: {len(mail['attachments'])}\n\n"
        f"{body[:MAX_BODY]}"
    )


def ask_claude(client: anthropic.Anthropic, mail: dict) -> dict:
    response = client.messages.create(
        model=MODEL,
        max_tokens=2000,
        system=SYSTEM,
        output_config={
            "effort": "low",  # klassificering behöver inte djup eftertanke
            "format": {"type": "json_schema", "schema": SCHEMA},
        },
        messages=[{"role": "user", "content": summarize(mail)}],
    )

    if response.stop_reason == "refusal":
        return {"kategori": "läsvärt", "sakerhet": "låg",
                "motivering": "Modellen avböjde att bedöma.", "av": "modell"}

    text = next(block.text for block in response.content if block.type == "text")
    verdict = json.loads(text)
    verdict["av"] = "modell"
    return verdict


def classify(redo: bool) -> None:
    client = anthropic.Anthropic(max_retries=5)
    files = sorted(CORPUS_DIR.glob("*.json"))

    by_rule = by_model = skipped = 0
    for number, path in enumerate(files, start=1):
        mail = json.loads(path.read_text(encoding="utf-8"))
        if mail.get("predicted") and not redo:
            skipped += 1
            continue

        verdict = rule_verdict(mail)
        if verdict:
            by_rule += 1
        else:
            verdict = ask_claude(client, mail)
            by_model += 1
            print(f"  {number}/{len(files)}  {verdict['kategori']:8} "
                  f"{mail['subject'][:45]}")

        mail["predicted"] = verdict
        path.write_text(json.dumps(mail, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{by_rule} av regeln, {by_model} av modellen, {skipped} redan gjorda.")


def report() -> None:
    mails = [json.loads(f.read_text(encoding="utf-8"))
             for f in sorted(CORPUS_DIR.glob("*.json"))]
    graded = [m for m in mails if m.get("predicted") and m["state"]]
    if not graded:
        print("Inget att jämföra - kör python classify.py först.")
        return

    print(f"{'':10}" + "".join(f"{k:>10}" for k in KATEGORIER) + "   (spalt = gissning)")
    for true_state in KATEGORIER:
        row = [sum(1 for m in graded
                   if m["state"] == true_state and m["predicted"]["kategori"] == guess)
               for guess in KATEGORIER]
        print(f"{true_state:10}" + "".join(f"{n:10}" for n in row))

    right = sum(1 for m in graded if m["state"] == m["predicted"]["kategori"])
    print(f"\ntotalt:      {right}/{len(graded)} ({right / len(graded):.0%})")

    hard = [m for m in graded if m["predicted"]["av"] == "modell"]
    if hard:
        right_hard = sum(1 for m in hard if m["state"] == m["predicted"]["kategori"])
        print(f"av modellen: {right_hard}/{len(hard)} ({right_hard / len(hard):.0%})"
              "   <- den siffran som betyder något")

    misses = [m for m in graded if m["state"] != m["predicted"]["kategori"]]
    if misses:
        print(f"\n{len(misses)} fel:")
        for mail in misses[:15]:
            print(f"  du: {mail['state']:8} den: {mail['predicted']['kategori']:8} "
                  f"{mail['subject'][:40]}")
            print(f"     {mail['predicted']['motivering'][:90]}")
        if len(misses) > 15:
            print(f"  ... och {len(misses) - 15} till")


def main() -> None:
    if "--rapport" in sys.argv:
        report()
        return

    classify(redo="--om" in sys.argv)
    print()
    report()


if __name__ == "__main__":
    main()
