"""Konfiguration. Läses från .env (se .env.example)."""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

PROJECT_ID = os.getenv("GCP_PROJECT_ID", "")
TOPIC_ID = os.getenv("PUBSUB_TOPIC", "gmail-notifications")
SUBSCRIPTION_ID = os.getenv("PUBSUB_SUBSCRIPTION", "gmail-pull")

TOPIC_PATH = f"projects/{PROJECT_ID}/topics/{TOPIC_ID}"
SUBSCRIPTION_PATH = f"projects/{PROJECT_ID}/subscriptions/{SUBSCRIPTION_ID}"

CREDENTIALS_FILE = BASE_DIR / "credentials.json"
TOKEN_FILE = BASE_DIR / "token.json"
STATE_FILE = BASE_DIR / "state.json"

if not PROJECT_ID:
    raise SystemExit("GCP_PROJECT_ID saknas. Kopiera .env.example till .env och fyll i.")
