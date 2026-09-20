"""Kontrollerar att allt är på plats, steg för steg.

    python check.py           - kollar konfiguration, inloggning, topic, subscription
    python check.py --publish - skickar dessutom en låtsasnotifiering till topicen,
                            så du kan testa listen.py utan att vänta på mail
"""
import json
import sys

from google.api_core.exceptions import NotFound, PermissionDenied
from google.cloud import pubsub_v1
from googleapiclient.discovery import build

from auth import get_credentials
from config import CREDENTIALS_FILE, PROJECT_ID, SUBSCRIPTION_ID, TOKEN_FILE, TOPIC_ID
from setup_pubsub import GMAIL_SERVICE_ACCOUNT, PUBLISHER_ROLE
from state import load_history_id

OK = "[OK]  "
FEL = "[FEL] "


def check_files() -> bool:
    print(f"{OK}Projekt-id: {PROJECT_ID}")
    if not CREDENTIALS_FILE.exists():
        print(f"{FEL}credentials.json saknas - ladda ner OAuth-klienten (Desktop app).")
        return False
    if CREDENTIALS_FILE.stat().st_size == 0:
        print(f"{FEL}credentials.json är tom - den ska innehålla nedladdad JSON.")
        return False
    print(f"{OK}credentials.json finns ({CREDENTIALS_FILE.stat().st_size} byte)")
    print(f"{OK if TOKEN_FILE.exists() else '[ - ] '}token.json "
          f"{'finns' if TOKEN_FILE.exists() else 'saknas - du får logga in nu'}")
    return True


def check_gmail(creds) -> tuple[str, str]:
    gmail = build("gmail", "v1", credentials=creds)
    profile = gmail.users().getProfile(userId="me").execute()
    print(f"{OK}Gmail svarar: {profile['emailAddress']} "
          f"({profile['messagesTotal']} mail, historyId={profile['historyId']})")
    return profile["emailAddress"], profile["historyId"]


def check_topic(publisher, topic_path: str) -> bool:
    try:
        publisher.get_topic(request={"topic": topic_path})
    except NotFound:
        print(f"{FEL}Topic saknas: {topic_path} - kör python setup_pubsub.py")
        return False
    print(f"{OK}Topic finns: {topic_path}")

    try:
        policy = publisher.get_iam_policy(request={"resource": topic_path})
    except PermissionDenied:
        print(f"{FEL}Får inte läsa IAM-policyn - är du ägare av projektet?")
        return False

    allowed = any(
        b.role == PUBLISHER_ROLE and GMAIL_SERVICE_ACCOUNT in b.members
        for b in policy.bindings
    )
    if not allowed:
        print(f"{FEL}Gmail saknar publish-rätt på topicen - kör python setup_pubsub.py")
        return False
    print(f"{OK}Gmail har publish-rätt på topicen")
    return True


def check_subscription(subscriber, subscription_path: str, topic_path: str) -> bool:
    try:
        subscription = subscriber.get_subscription(
            request={"subscription": subscription_path}
        )
    except NotFound:
        print(f"{FEL}Subscription saknas: {subscription_path} - kör python setup_pubsub.py")
        return False

    if subscription.push_config.push_endpoint:
        print(f"{FEL}Detta är en push-subscription, inte pull.")
        return False

    print(f"{OK}Pull-subscription finns: {subscription_path}")
    if subscription.topic != topic_path:
        print(f"{FEL}Den pekar på fel topic: {subscription.topic}")
        return False
    return True


def publish_test_message(publisher, topic_path: str, email: str, history_id: str) -> None:
    data = json.dumps({"emailAddress": email, "historyId": history_id}).encode()
    future = publisher.publish(topic_path, data)
    print(f"\n{OK}Skickade testnotifiering (id={future.result()})")
    print("      Kör python listen.py i ett annat fönster - den ska plocka upp den.")


def main() -> None:
    if not check_files():
        return

    creds = get_credentials()
    email, history_id = check_gmail(creds)

    publisher = pubsub_v1.PublisherClient(credentials=creds)
    topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)
    subscriber = pubsub_v1.SubscriberClient(credentials=creds)
    subscription_path = subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_ID)

    ok = check_topic(publisher, topic_path)
    ok = check_subscription(subscriber, subscription_path, topic_path) and ok
    subscriber.close()

    saved = load_history_id()
    print(f"{OK if saved else '[ - ] '}Sparat historyId: {saved or 'inget ännu (sätts av watch.py)'}")
    print("\nObs: det går inte att fråga Gmail om bevakningen är aktiv - "
          "kör python watch.py om du är osäker.")

    if ok and "--publish" in sys.argv:
        publish_test_message(publisher, topic_path, email, saved or history_id)


if __name__ == "__main__":
    main()
