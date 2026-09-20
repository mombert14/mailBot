"""OAuth mot Google. Ger credentials för både Gmail och Pub/Sub."""
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from config import CREDENTIALS_FILE, TOKEN_FILE

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/pubsub",
]


def get_credentials() -> Credentials:
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not CREDENTIALS_FILE.exists() or CREDENTIALS_FILE.stat().st_size == 0:
            raise SystemExit(
                f"{CREDENTIALS_FILE.name} saknas eller är tom. Ladda ner "
                "OAuth-klienten (Desktop app) från Google Cloud Console - "
                "filen ska innehålla färdig JSON, skapa den inte själv."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
        creds = flow.run_local_server(port=0)

    TOKEN_FILE.write_text(creds.to_json())
    return creds


if __name__ == "__main__":
    get_credentials()
    print("Inloggad. Token sparad i token.json")
