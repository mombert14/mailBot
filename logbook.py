"""Loggar varje beslut boten fattar, och visar loggen.

    python logbook.py            # sammanfattning + de 30 senaste besluten
    python logbook.py --alla     # alla beslut
    python logbook.py --osakra   # bara de modellen inte var säker på
    python logbook.py --brus     # bara en kategori (--brus/--lasvart/--svar)

Loggen är en JSONL-fil: ett beslut per rad, alltid tillagd sist. Den klarar
att programmet kraschar mitt i, och går att läsa med vilket verktyg som helst.
"""
import json
import sys
from datetime import datetime

from config import BASE_DIR

LOG_FILE = BASE_DIR / "beslut.jsonl"
DEFAULT_SHOWN = 30
EXCERPT = 150


def record(mail: dict, verdict: dict, actions: list[str], allowed: set[str]) -> None:
    """Skriver ett beslut sist i loggen."""
    entry = {
        "tid": datetime.now().isoformat(timespec="seconds"),
        "id": mail["id"],
        "from": mail["from"],
        "subject": mail["subject"],
        "kategori": verdict["kategori"],
        "sakerhet": verdict["sakerhet"],
        "av": verdict["av"],
        "motivering": verdict["motivering"],
        "atgarder": actions,
        "skarpt": bool(allowed),
        "lage": sorted(allowed) or ["torrläge"],
        "utdrag": " ".join(mail["body"].split())[:EXCERPT],
    }
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")


def load() -> list[dict]:
    if not LOG_FILE.exists():
        return []
    return [
        json.loads(line)
        for line in LOG_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def summary(entries: list[dict]) -> None:
    print(f"{len(entries)} beslut, {entries[0]['tid'][:16]} - {entries[-1]['tid'][:16]}\n")

    for kategori in ("brus", "läsvärt", "svar"):
        grupp = [e for e in entries if e["kategori"] == kategori]
        if not grupp:
            continue
        av_regel = sum(1 for e in grupp if e["av"] == "regel")
        osakra = sum(1 for e in grupp if e["sakerhet"] != "hög")
        print(f"  {kategori:10} {len(grupp):4}   "
              f"varav {av_regel} av regeln, {osakra} osäkra")

    skarpa = sum(1 for e in entries if e.get("skarpt"))
    print(f"\n  {skarpa} fattade i skarpt läge, {len(entries) - skarpa} i torrläge")

    lagen = {tuple(e.get("lage", ["torrläge"])) for e in entries}
    if len(lagen) > 1:
        print("  lägen som förekommit: "
              + " | ".join(", ".join(l) for l in sorted(lagen)))

    osakra = [e for e in entries if e["sakerhet"] != "hög"]
    if osakra:
        print(f"\n  Granska särskilt de {len(osakra)} osäkra: python logbook.py --osakra")


def show(entries: list[dict]) -> None:
    for entry in entries:
        flagga = " " if entry["sakerhet"] == "hög" else "?"
        print(f"\n{flagga} {entry['tid'][:16]}  {entry['kategori'].upper()}"
              f"  ({entry['sakerhet']}, {entry['av']})")
        print(f"  {entry['from'][:52]}")
        print(f"  {entry['subject'][:60]}")
        print(f"  {entry['motivering'][:75]}")
        for atgard in entry["atgarder"]:
            print(f"    · {atgard[:70]}")


def main() -> None:
    entries = load()
    if not entries:
        raise SystemExit(f"Ingen logg än. Den skapas när listen.py bedömt sitt första mail.\n{LOG_FILE}")

    valda = entries
    for flagga, kategori in (("--brus", "brus"), ("--lasvart", "läsvärt"), ("--svar", "svar")):
        if flagga in sys.argv:
            valda = [e for e in valda if e["kategori"] == kategori]

    if "--osakra" in sys.argv:
        valda = [e for e in valda if e["sakerhet"] != "hög"]

    summary(entries)

    if "--alla" not in sys.argv and len(valda) > DEFAULT_SHOWN:
        print(f"\nVisar de {DEFAULT_SHOWN} senaste av {len(valda)}. Allt: --alla")
        valda = valda[-DEFAULT_SHOWN:]

    show(valda)


if __name__ == "__main__":
    main()
