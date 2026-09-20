"""Skapar Pub/Sub-topic + pull-subscription och ger Gmail rätt att publicera.

Kör en gång:  python setup_pubsub.py
"""
from google.api_core.exceptions import AlreadyExists
from google.cloud import pubsub_v1

from auth import get_credentials
from config import PROJECT_ID, SUBSCRIPTION_ID, TOPIC_ID

# Kontot som Gmail API:t publicerar notifieringar ifrån.
GMAIL_SERVICE_ACCOUNT = "serviceAccount:gmail-api-push@system.gserviceaccount.com"
PUBLISHER_ROLE = "roles/pubsub.publisher"


def create_topic(publisher, topic_path: str) -> None:
    try:
        publisher.create_topic(request={"name": topic_path})
        print(f"Skapade topic: {topic_path}")
    except AlreadyExists:
        print(f"Topic finns redan: {topic_path}")


def allow_gmail_to_publish(publisher, topic_path: str) -> None:
    policy = publisher.get_iam_policy(request={"resource": topic_path})

    binding = next((b for b in policy.bindings if b.role == PUBLISHER_ROLE), None)
    if binding is None:
        binding = policy.bindings.add()
        binding.role = PUBLISHER_ROLE

    if GMAIL_SERVICE_ACCOUNT in binding.members:
        print("Gmail har redan publish-rättighet.")
        return

    binding.members.append(GMAIL_SERVICE_ACCOUNT)
    publisher.set_iam_policy(request={"resource": topic_path, "policy": policy})
    print("Gav Gmail publish-rättighet på topicen.")


def create_subscription(subscriber, subscription_path: str, topic_path: str) -> None:
    try:
        subscriber.create_subscription(
            request={
                "name": subscription_path,
                "topic": topic_path,
                "ack_deadline_seconds": 60,
            }
        )
        print(f"Skapade pull-subscription: {subscription_path}")
    except AlreadyExists:
        print(f"Subscription finns redan: {subscription_path}")


def main() -> None:
    creds = get_credentials()

    publisher = pubsub_v1.PublisherClient(credentials=creds)
    topic_path = publisher.topic_path(PROJECT_ID, TOPIC_ID)
    create_topic(publisher, topic_path)
    allow_gmail_to_publish(publisher, topic_path)

    subscriber = pubsub_v1.SubscriberClient(credentials=creds)
    subscription_path = subscriber.subscription_path(PROJECT_ID, SUBSCRIPTION_ID)
    create_subscription(subscriber, subscription_path, topic_path)
    subscriber.close()

    print("\nKlart. Nästa steg: python watch.py")


if __name__ == "__main__":
    main()
