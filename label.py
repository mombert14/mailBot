"""Märker upp korpuset - ett mail i taget, en tangent per mail.

    python label.py          # bara omärkta mail
    python label.py --alla   # gå igenom allt, även redan märkt

Varje tangenttryck sparas direkt i mailets fil, så det går att avbryta
med q och fortsätta senare.
"""
import json
import re
import shutil
import sys
import textwrap
from pathlib import Path

from config import BASE_DIR

CORPUS_DIR = BASE_DIR / "corpus"
EXCERPT = 400  # tecken av brödtexten som visas

KEYS = {"b": "brus", "l": "läsvärt", "s": "svar"}

try:
    from msvcrt import getwch as read_key  # Windows: en tangent, ingen retur
except ImportError:

    def read_key() -> str:
        return (input() or " ")[0]


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, mail: dict) -> None:
    path.write_text(json.dumps(mail, ensure_ascii=False, indent=2), encoding="utf-8")


def excerpt(body: str, width: int) -> list[str]:
    """Några läsbara rader ur brödtexten, utan tracking-länkar."""
    text = re.sub(r"https?://\S+", " ", body)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return ["(ingen läsbar text)"]
    return textwrap.wrap(text[:EXCERPT], width=width)[:6]


def show(mail: dict, position: int, total: int) -> None:
    width = min(shutil.get_terminal_size().columns, 90) - 2

    category = next(
        (l.replace("CATEGORY_", "") for l in mail["labels"] if l.startswith("CATEGORY_")),
        "-",
    )
    facts = [
        category,
        "unsub: ja" if mail["list_unsubscribe"] else "unsub: nej",
        f"{len(mail['body'])} tecken",
        mail["date"][:16],
    ]
    if mail["state"]:
        facts.append(f"NU: {mail['state']}")

    print()
    print("─" * width + f" {position}/{total}")
    print(mail["from"][:width])
    print(mail["subject"][:width])
    print(" · ".join(facts))
    print()
    for line in excerpt(mail["body"], width):
        print("  " + line)
    print()
    print("  [b]rus   [l]äsvärt   [s]var   [mellanslag] hoppa   [u] tillbaka   [q] avsluta")


def summary(files: list[Path]) -> None:
    counts: dict[str, int] = {}
    for path in files:
        counts[load(path)["state"] or "omärkt"] = counts.get(load(path)["state"] or "omärkt", 0) + 1

    print("\nStällning:")
    for state in ("brus", "läsvärt", "svar", "omärkt"):
        if state in counts:
            print(f"  {state:10} {counts[state]:3}")


def main() -> None:
    show_all = "--alla" in sys.argv
    files = sorted(CORPUS_DIR.glob("*.json"))
    if not files:
        raise SystemExit("corpus/ är tom - kör python dump_corpus.py först.")

    queue = [path for path in files if show_all or not load(path)["state"]]
    already_done = len(files) - len(queue)

    if not queue:
        print(f"Alla {len(files)} mail är redan uppmärkta.")
        summary(files)
        return

    index = 0
    while index < len(queue):
        path = queue[index]
        mail = load(path)
        show(mail, already_done + index + 1, len(files))

        key = read_key().lower()
        if key == "q":
            break
        if key == "u":
            index = max(0, index - 1)
            continue
        if key in KEYS:
            mail["state"] = KEYS[key]
            save(path, mail)

        index += 1  # allt annat = hoppa över utan att märka

    summary(files)


if __name__ == "__main__":
    main()
