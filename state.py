"""Sparar senaste historyId mellan körningar."""
import json

from config import STATE_FILE


def load_history_id() -> str | None:
    if not STATE_FILE.exists():
        return None
    return json.loads(STATE_FILE.read_text()).get("history_id")


def save_history_id(history_id: str) -> None:
    STATE_FILE.write_text(json.dumps({"history_id": str(history_id)}))
