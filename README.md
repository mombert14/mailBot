# MailBot

Bevakar Gmail-inkorgen, bedömer varje inkommande mail och gör något åt det:

| Kategori | Åtgärd |
|---|---|
| `brus` | Papperskorgen, och avregistrering om avsändaren stödjer det |
| `läsvärt` | Ingenting — ligger kvar i inkorgen |
| `svar` | Ett utkast till svar skapas i tråden, i din egen ton |

Ingenting skickas någonsin automatiskt. Svar hamnar alltid som utkast.

## Hur det hänger ihop

```
nytt mail → Gmail users.watch() → Pub/Sub topic → pull-subscription → listen.py
                                                                          ↓
                                    regel (List-Unsubscribe) eller gpt-4o-mini
                                                                          ↓
                                                    act.py: släng / lämna / drafta
```

Notifieringen från Gmail innehåller bara `emailAddress` och `historyId`. Med det
numret frågar `listen.py` vad som hänt sedan sist och hämtar mailen själv.

Två tredjedelar av inkorgen avgörs av en enda regel: mail med en
`List-Unsubscribe`-header är massutskick. På ett uppmärkt korpus om 200 mail
stämde det i 126 fall av 126. Resten går till modellen, som träffade rätt i
96 % av fallen.

## Installation

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env      # fyll i GCP_PROJECT_ID och OPENAI_API_KEY
```

Dessutom behövs `credentials.json` — en OAuth-klient av typen **Desktop app**
från Google Cloud Console, i projektets rot. Se avsnittet *Google Cloud* nedan.

## Kom igång

```powershell
python check.py           # kollar att allt är på plats, loggar in
python setup_pubsub.py    # skapar topic och pull-subscription (en gång)
python listen.py          # bevakar inkorgen i torrläge
```

## Driftsättning

Boten kör lokalt. Pub/Sub sparar notifieringar i sju dagar, så en avstängd
natt kostar ingenting — den arbetar ikapp vid start.

**Schemaläggaren:** `Win+R` → `taskschd.msc` → *Skapa aktivitet*.

- **Utlösare:** Vid inloggning
- **Åtgärder:** `kor_bot.bat`, med *Börja i* satt till projektmappen
- **Villkor:** avmarkera "Starta endast om datorn är ansluten till elnätet"
- **Inställningar:** avmarkera "Stoppa aktiviteten om den körs längre än 3 dagar"

De två sista är lätta att missa och gör att boten annars stannar av sig själv.

### Trappan till skarpt läge

Åtgärderna slås på var för sig, i stigande oåterkallelighet. Ändra sista raden
i `kor_bot.bat`:

```
python listen.py                    torrläge — visar bara vad som skulle hända
python listen.py --utkast           draftar svar (kan raderas)
python listen.py --utkast --sopa    + slänger brus (30 dagar i papperskorgen)
python listen.py --skarp            + avregistrerar (går inte att ångra)
```

Kör en nivå i taget, minst en vecka. Granska däremellan:

```powershell
python logbook.py            # sammanfattning + de senaste besluten
python logbook.py --osakra   # bara det modellen tvekade om
```

Boten agerar bara när den är säker. Lägre säkerhet loggas men lämnas orörd
(`ACT_ON` i `act.py`).

`never_unsubscribe.txt` listar avsändare som får slängas men aldrig
avregistreras. Den är tom som standard.

## Filerna

| Fil | Ansvar |
|---|---|
| `config.py` | Läser `.env`, bygger sökvägar |
| `auth.py` | OAuth mot Google, sparar `token.json` |
| `setup_pubsub.py` | Skapar topic, IAM-binding och pull-subscription |
| `watch.py` | `users.watch()` — kopplar inkorgen till topicen |
| `mail.py` | Hämtar ett mail och gör om det till en platt post |
| `state.py` | Senaste `historyId` |
| `listen.py` | Huvudprogrammet: bevakar, bedömer, agerar |
| `classify.py` | Regeln och modellanropet |
| `act.py` | Vad varje kategori leder till |
| `draft.py` | Skriver utkast i din ton |
| `logbook.py` | Beslutsloggen (`beslut.jsonl`) |
| `check.py` | Diagnostik |
| `dump_corpus.py` | Sparar inkorgen lokalt för utveckling |
| `label.py` | Uppmärkning för hand, en tangent per mail |

## Google Cloud

Engångsjobb i webbläsaren:

1. Skapa ett projekt, notera **projekt-id**
2. Aktivera **Gmail API** och **Cloud Pub/Sub API**
3. Google Auth Platform → **Audience** → lägg till din adress som testanvändare
4. **Clients** → Create client → **Desktop app** → ladda ner som `credentials.json`

I *Testing* upphör Googles refresh-tokens efter sju dagar. Slutar boten logga
och `bot.out` ber om inloggning: publicera appen under **Audience**.

## Hemligheter

`credentials.json`, `token.json`, `.env`, `state.json`, `corpus/`,
`beslut.jsonl` och `bot.out` ligger i `.gitignore` och ska aldrig checkas in.
