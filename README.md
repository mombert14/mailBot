# MailBot

Watches your Gmail inbox, judges every incoming mail and does something about it:

| Category | Action |
|---|---|
| `brus` | The trash, and unsubscribes if the sender supports it |
| `läsvärt` | Nothing — stays in the inbox |
| `svar` | A draft reply is created in the thread, in your own tone |

How to get your own copy working:


-----------------Google cloud setup------------------
1. Go to https://console.cloud.google.com/apis/credentials with the account you want notifications for.
2. Click "Create OAuth client ID" and pick desktop app
3. Copy the "Client id" into GCP_PROJECT_ID
GCP_PROJECT_ID=


PUBSUB_TOPIC=gmail-notifications
PUBSUB_SUBSCRIPTION=gmail-pull

-----------------OPENAI setup------------------
NOTE: This application currently only works with openai. Change the code if you want a different model. This program runs GPT-4o mini.
OPENAI_API_KEY=

-----------------Discord setup------------------
1. Create a server
2. Click the settings for the channel.
3. Pick integrations and create a webhook.
4. Paste it below.
DISCORD_WEBHOOK=

Enjoy a sorted inbox.

Best regards -
Frithjof
