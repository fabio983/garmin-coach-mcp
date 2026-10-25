# garmin-coach-mcp

**Claude legge i tuoi dati di corsa Garmin e, se vuoi, ti mette gli allenamenti sull'orologio.**

`garmin-coach-mcp` è un piccolo servizio self-hosted che tiene un archivio locale delle tue attività
Garmin Connect (riepiloghi, lap e dati secondo per secondo dai file FIT originali) e lo rende disponibile a
[Claude Desktop](https://claude.ai/download) tramite il [Model Context Protocol](https://modelcontextprotocol.io).

I dati vengono letti con la **[Connect Personal API](https://developer.garmin.com/gc-developer-program/personal/personal-api)
ufficiale di Garmin**, che è **in sola lettura**. La scrittura su Garmin, cioè creare allenamenti strutturati e
programmarli nel calendario, è disponibile tramite un **modulo opzionale della community** da attivare
esplicitamente (vedi [Scrittura (opzionale)](#scrittura-opzionale)).

Basta esportare CSV dopo ogni corsa: chiedi e basta.

> *"Sincronizza e analizza la corsa di stamattina: com'è andata la deriva cardiaca negli ultimi 5 km?"*
> *"Confronta i lunghi delle ultime 8 settimane: passo, frequenza cardiaca, cadenza."*
> *"La seduta di mercoledì l'ho eseguita come era pianificata?"*
> *"Mettimi sull'orologio la seduta di venerdì: 15' facili, 3 × 2 km a 5:40-5:45 con 2' di corsa lenta, 10' di defaticamento."* (scrittura)

🇬🇧 [English version](README.md)

---

## Indice

- [Cosa fa](#cosa-fa)
- [Sola lettura di default, scrittura opzionale](#sola-lettura-di-default-scrittura-opzionale)
- [Come funziona](#come-funziona)
- [Requisiti](#requisiti)
- [Installazione](#installazione)
- [Collegare Claude Desktop](#collegare-claude-desktop)
- [Scrittura (opzionale)](#scrittura-opzionale)
- [Note personali per Claude](#note-personali-per-claude)
- [Strumenti](#strumenti)
- [Allenamenti strutturati](#allenamenti-strutturati)
- [Configurazione](#configurazione)
- [Manutenzione](#manutenzione)
- [Risoluzione problemi](#risoluzione-problemi)
- [Dati, privacy e sicurezza](#dati-privacy-e-sicurezza)
- [Limiti e avvertenze](#limiti-e-avvertenze)
- [Ringraziamenti](#ringraziamenti)

---

## Cosa fa

**Il tuo storico, sempre disponibile** (API ufficiale)
- Importa una volta lo storico delle attività, poi scarica quelle nuove ogni 30 minuti (o su richiesta).
- Per ogni corsa salva il FIT originale ed estrae lap e dati secondo per secondo: passo, frequenza cardiaca,
  cadenza, dinamiche di corsa (tempo di contatto e bilanciamento, oscillazione e rapporto verticale,
  lunghezza del passo), potenza, altimetria, GPS.
- Collega ogni attività all'allenamento pianificato da cui è stata eseguita.

**Strumenti pronti per l'analisi** (API ufficiale)
- Singola attività: riepilogo, lap (stesso contenuto del CSV per lap di Garmin), tempo nelle fasce cardiache,
  recupero cardiaco a 60", allenamento pianificato.
- Serie temporali a qualsiasi risoluzione: deriva cardiaca, crisi, analisi delle ripetute.
- Riepiloghi settimanali: volume, lungo, carico, distribuzione dell'intensità.
- SQL in sola lettura per tutto il resto (andamenti su mesi, confronti, record).
- Annotazioni per quello che Garmin non sa o sbaglia: temperatura reale, tapis roulant, scarpe, RPE, note.

**Allenamenti sull'orologio** (modulo opzionale della community)
- Claude scrive allenamenti di corsa strutturati (riscaldamento, ripetute, recuperi, defaticamento, target di passo
  o di frequenza cardiaca) e li programma nel calendario Garmin: arrivano sull'orologio al sync successivo.
- Sempre anteprima prima, caricamento solo dopo il tuo ok.
- Aggiunge anche il passo corretto per la pendenza su ogni lap e le scarpe assegnate su Garmin Connect.

---

## Sola lettura di default, scrittura opzionale

| | Personal API ufficiale (default) | Modulo della community (opzionale) |
|---|---|---|
| Fornito da | Garmin | [python-garminconnect](https://github.com/cyberjunky/python-garminconnect) (API non ufficiale) |
| Accesso | **Sola lettura** | Lettura **e scrittura** |
| Configurazione | Una chiave Personal API nel `.env` | `ENABLE_GARMINCONNECT=true` + login interattivo (MFA supportato) |
| Attività, FIT originali, lap, dati al secondo | ✅ | (usato solo se manca la chiave API) |
| Allenamento pianificato collegato a ogni attività | ✅ | – |
| Passo corretto per pendenza per lap, scarpe da Garmin Connect | – | ✅ |
| Creare / programmare / eliminare allenamenti strutturati | ❌ non disponibile | ✅ |
| Stabilità | Ufficiale, documentata | Può smettere di funzionare se Garmin cambia la sua API privata |

Se vuoi solo che Claude analizzi le tue corse, basta l'API ufficiale.
Attiva il modulo della community solo se vuoi anche che Claude scriva allenamenti su Garmin.

---

## Come funziona

```mermaid
flowchart LR
    PA[(Garmin Connect<br/>Personal API<br/>ufficiale, sola lettura)] -- attività + FIT --> S
    GC[(Garmin Connect<br/>modulo community<br/>opzionale, lettura/scrittura)] -. allenamenti, GAP, scarpe .- S
    subgraph Server["Container Docker (homelab / NAS / PC)"]
        S[Sincronizzazione] --> DB[(SQLite + file FIT)]
        DB --> M[Server MCP :8765/mcp]
    end
    M -. crea/programma allenamenti .-> GC
    CD[Claude Desktop] -- mcp-remote, LAN + token --> M
```

- Tutto resta in locale nella cartella `./data`: niente viene inviato altrove.
- Claude Desktop si collega al container sulla rete di casa tramite
  [`mcp-remote`](https://github.com/geelen/mcp-remote), con un token.

---

## Requisiti

| Dove | Cosa |
|---|---|
| Server (una macchina sempre accesa: VM homelab, NAS, Raspberry Pi 4/5, PC) | Docker + Docker Compose |
| Il tuo computer | [Claude Desktop](https://claude.ai/download) e [Node.js](https://nodejs.org) LTS (per `npx`) |
| Garmin | Un account Garmin Connect e una [chiave Personal API](https://developer.garmin.com/gc-developer-program/personal/personal-faq/) |

Server e computer devono stare sulla stessa rete (o raggiungersi via VPN).

---

## Installazione

### 1. Scarica il codice sul server

```bash
git clone https://github.com/fabio983/garmin-coach-mcp.git
cd garmin-coach-mcp
```

### 2. Crea una chiave Personal API di Garmin

1. Accedi a Garmin Connect dal web e apri
   **Impostazioni → Personal API** ([link diretto](https://connect.garmin.com/app/settings/personalApiToken)).
2. Leggi e accetta i termini, scegli la scadenza (da 30 giorni a 1 anno) e crea la chiave.
3. Copiala subito: Garmin la mostra una volta sola.

### 3. Configura

```bash
cp .env.example .env
openssl rand -hex 32        # copia il risultato in MCP_TOKEN
nano .env                   # incolla la chiave in GARMIN_PERSONAL_API_KEY, imposta TZ, BACKFILL_FROM, HR_BANDS...
```

Tutte le opzioni sono in [Configurazione](#configurazione).

### 4. Build e avvio

```bash
docker compose build
docker compose up -d
docker compose logs -f
```

Al primo avvio importa lo storico da `BACKFILL_FROM` (pochi secondi per corsa, con pause tra le chiamate).
Vedrai una riga `Details <id> (running) ok` per corsa e alla fine `Auto sync: ok`.

Verifica dal computer che il server risponda:

```bash
curl http://IP-SERVER:8765/healthz      # → ok
```

Facoltativo: `tools/probe_personal_api.py` verifica la chiave e cosa restituisce l'API,
vedi [tools/README.md](tools/README.md).

---

## Collegare Claude Desktop

1. Installa **Node.js LTS** sul computer (Windows: `winget install OpenJS.NodeJS.LTS`), poi apri un nuovo terminale
   e controlla `node -v`.
2. In Claude Desktop apri **Impostazioni → Sviluppatore → Modifica configurazione**. Si apre `claude_desktop_config.json`:
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
3. Aggiungi il blocco `garmin-coach` dentro `mcpServers`
   (vedi [`examples/claude_desktop_config.json`](examples/claude_desktop_config.json)):

   ```json
   {
     "mcpServers": {
       "garmin-coach": {
         "command": "npx",
         "args": ["-y", "mcp-remote@latest", "http://IP-SERVER:8765/mcp",
                  "--allow-http", "--transport", "http-only",
                  "--header", "Authorization:${AUTH_HEADER}"],
         "env": { "AUTH_HEADER": "Bearer IL_TUO_MCP_TOKEN" }
       }
     }
   }
   ```

   Se il file contiene già altre chiavi (per esempio `preferences`), lasciale: `mcpServers` va al primo livello,
   separato da una virgola. Se `mcpServers` esiste già, aggiungi `garmin-coach` al suo interno.
4. **Chiudi Claude del tutto** (su Windows anche dall'icona in basso a destra) e riaprilo.
   Chiudi Claude *prima* di salvare il file, altrimenti uscendo potrebbe sovrascrivere la modifica.
5. In **Impostazioni → Sviluppatore** deve comparire `garmin-coach` *in esecuzione*.
6. Apri una **nuova** chat e chiedi: *"Com'è messo il mio archivio Garmin?"*

La forma `Authorization:${AUTH_HEADER}` (senza spazio dopo i due punti) evita un problema noto con gli spazi
negli argomenti su Windows.

---

## Scrittura (opzionale)

La Personal API ufficiale è **in sola lettura**: con lei sola Claude analizza i tuoi dati ma non può creare
né programmare allenamenti. Per avere anche la scrittura attiva il modulo della community. Usa
[python-garminconnect](https://github.com/cyberjunky/python-garminconnect), che parla con l'API privata di
Garmin Connect con lo stesso login dell'app per smartphone.

> **Prima di attivarlo:** non è un'interfaccia ufficiale Garmin, può smettere di funzionare quando Garmin cambia
> la sua API privata e fa il login con le credenziali del tuo account. Usalo solo con il tuo account.

### Attivazione, passo per passo

1. **Modifica `.env`** sul server:

   ```bash
   ENABLE_GARMINCONNECT=true
   ```

2. **Ricrea il container**, così legge la nuova impostazione (un semplice `restart` non rilegge `.env`):

   ```bash
   docker compose up -d
   ```

3. **Fai il login una volta** a Garmin Connect dal container:

   ```bash
   docker compose run --rm garmin-coach login
   ```

   Inserisci email, password e, se attivo, il codice MFA. I token vengono salvati in `data/tokens/`; la password
   non viene salvata. Avvisi come `mobile+cffi returned 429` sono normali, purché il comando finisca con `Login OK`.

4. **Riavvia il servizio**, così usa i nuovi token:

   ```bash
   docker compose restart
   ```

5. **Riavvia Claude Desktop** (chiudilo del tutto e riaprilo).

6. **Verifica** in una nuova chat: chiedi *"Com'è messo il mio archivio Garmin?"*: deve risultare
   `write access (community module): enabled`. Poi chiedi *"Quali allenamenti ho nel calendario Garmin?"*.

Da qui in poi Claude può creare allenamenti (mostrando sempre prima l'anteprima), e i sync successivi aggiungono
anche il passo corretto per la pendenza su ogni lap e le scarpe assegnate su Garmin Connect.

### Disattivazione

Imposta `ENABLE_GARMINCONNECT=false`, lancia `docker compose up -d` e, se vuoi, cancella
`data/tokens/garmin_tokens.json`. Gli strumenti per gli allenamenti risponderanno che la scrittura è disattivata;
la lettura tramite API ufficiale non cambia.

---

## Note personali per Claude

Claude lavora meglio se conosce il tuo contesto: sensori, zone cardiache, cadenza obiettivo,
a cosa servono le varie scarpe. Scrivilo in `data/athlete.md`:

```bash
cp examples/athlete.example.md data/athlete.md
nano data/athlete.md
docker compose restart
```

Il file viene aggiunto alle istruzioni che il server dà a Claude in ogni chat. Sta in `data/`,
quindi non finisce mai nel repository.

---

## Strumenti

| Strumento | Cosa fa | Richiede |
|---|---|---|
| `sync_garmin` | Scarica subito le attività nuove (`full=true` reimporta tutto in background) | API ufficiale |
| `sync_status` | Sorgenti dati, conteggi dell'archivio, periodo coperto, esito degli ultimi sync | – |
| `list_activities` | Attività in un periodo, filtrabili per tipo | – |
| `get_activity` | Riepilogo, lap, HRR60, tempo nelle fasce, allenamento pianificato, annotazioni (`latest`, una data o un id) | – |
| `get_activity_series` | Dati secondo per secondo mediati ogni N secondi, anche su una finestra di tempo | – |
| `training_summary` | Riepilogo settimanale: uscite, km, tempo, passo, lungo, carico, distribuzione FC | – |
| `annotate_activity` | Salva temperatura reale, umidità, tapis, scarpe, tipo seduta, RPE, HRR, note | – |
| `query_sql` | SQL in sola lettura sull'archivio (schema nella descrizione dello strumento) | – |
| `create_workout` | Crea un allenamento strutturato: anteprima → conferma → caricamento e programmazione | ✍️ modulo community |
| `get_workout` | Mostra i passi di un allenamento salvato su Garmin Connect | ✍️ modulo community |
| `list_workouts` | Allenamenti in calendario e ultimi della libreria | ✍️ modulo community |
| `delete_workout` | Toglie dal calendario e/o elimina un allenamento (solo su tua richiesta) | ✍️ modulo community |

Gli strumenti segnati con – lavorano sull'archivio locale. Senza il modulo della community gli strumenti ✍️
rispondono che la scrittura è disattivata e spiegano come attivarla (`create_workout` mostra comunque l'anteprima).

---

## Allenamenti strutturati

*Richiede la [scrittura](#scrittura-opzionale).*

Claude costruisce gli allenamenti da una semplice lista di passi. Non serve scriverla a mano:
descrivi la seduta a parole e Claude la traduce. Per riferimento:

```json
[
  {"kind": "warmup", "time": "15:00", "hr": "120-145", "note": "facile"},
  {"repeat": 4, "steps": [
    {"kind": "interval", "distance_m": 100, "note": "allungo"},
    {"kind": "recovery", "time": "0:45", "note": "cammina"}
  ]},
  {"repeat": 3, "steps": [
    {"kind": "interval", "distance_km": 2, "pace": "5:40-5:45"},
    {"kind": "recovery", "time": "2:00", "note": "corsa lenta"}
  ]},
  {"kind": "cooldown", "time": "10:00"}
]
```

| Campo | Valori |
|---|---|
| `kind` | `warmup`, `interval`, `recovery`, `rest`, `cooldown`, `other` |
| durata (una) | `time` (`"mm:ss"`), `distance_km`, `distance_m`, `lap: true` (fino al tasto lap) |
| target (facoltativo, uno) | `pace` (`"m:ss-m:ss"` al km) oppure `hr` (`"min-max"` bpm) |
| `note` | Testo breve mostrato sull'orologio in quel passo |
| ripetizione | `{"repeat": N, "steps": [...]}`, anche annidate |

I target Garmin hanno sempre due limiti. Per "più lento di 7:00/km" usa un range largo (es. `7:00-7:45`)
o un tetto di frequenza cardiaca (es. `hr: "120-145"`).

Flusso: Claude mostra un'**anteprima**, tu confermi, poi carica l'allenamento e (con una data) lo programma.
Con `replace_workout_id` riscrive un allenamento esistente mantenendo le date in calendario.

---

## Configurazione

Tutte le impostazioni stanno in `.env` (vedi [`.env.example`](.env.example)). Dopo una modifica lancia `docker compose up -d`.

| Variabile | Default | Descrizione |
|---|---|---|
| `MCP_TOKEN` | – | Token richiesto dall'endpoint MCP. **Da impostare.** |
| `GARMIN_PERSONAL_API_KEY` | – | Chiave Personal API ufficiale (sorgente dati, sola lettura). **Da impostare.** |
| `ENABLE_GARMINCONNECT` | `false` | Attiva il modulo opzionale della community (scrittura, GAP per lap, scarpe) |
| `GARMIN_EMAIL` / `GARMIN_PASSWORD` | – | Solo modulo community: re-login automatico (non con MFA) |
| `TZ` | – | Fuso orario, es. `Europe/Rome` |
| `BACKFILL_FROM` | `2024-01-01` | Data di inizio della prima importazione |
| `SYNC_INTERVAL_MIN` | `30` | Intervallo del sync automatico (0 = solo su richiesta) |
| `REQUEST_DELAY_S` | `1.5` | Pausa tra le chiamate a Garmin |
| `HR_BANDS` | `135,150,160,170` | Soglie inferiori delle fasce FC 2..N per il tempo in zona |
| `DETAIL_TYPE_MATCH` | `run` | Tipi di attività (sottostringa del `typeKey` Garmin) per cui scaricare FIT/lap/record |
| `ATHLETE_FILE` | `/data/athlete.md` | Note personali aggiunte alle istruzioni per Claude |
| `MCP_PORT` | `8765` | Porta nel container |

Se `GARMIN_PERSONAL_API_KEY` è vuota e il modulo della community è attivo, le attività vengono lette tramite il
modulo (il comportamento della versione 0.1).

---

## Manutenzione

| Operazione | Comando |
|---|---|
| Aggiornamento | `git pull && docker compose up -d --build`, poi riavvia Claude Desktop |
| Chiave Personal API scaduta (`auth_required` in `sync_status`) | Crea una nuova chiave su Garmin Connect, aggiorna `.env`, `docker compose up -d` |
| Token del modulo community scaduti | `docker compose run --rm garmin-coach login && docker compose restart` |
| Importare lo storico più vecchio | `docker compose exec garmin-coach python -m app sync --since 2017-01-01` |
| Sync manuale | `docker compose exec garmin-coach python -m app sync [--since 2026-01-01] [--full]` |
| Rigenerare lap/record dai FIT | `docker compose exec garmin-coach python -m app reparse` |
| Backup | Copia la cartella `data/` |
| Log | `docker compose logs -f` |

Garmin ti manda un'email circa una settimana prima della scadenza della chiave Personal API.

---

## Risoluzione problemi

| Sintomo | Causa / soluzione |
|---|---|
| `sync_status`: `auth_required`, *Personal API rejected the key* | Chiave scaduta, revocata o copiata male. Creane una nuova, aggiorna `.env`, poi `docker compose up -d`. |
| Claude dice che per gli allenamenti serve la scrittura | Normale con la sola API ufficiale (sola lettura). Attiva il [modulo della community](#scrittura-opzionale). |
| Avvisi `429` durante il `login` | Normali se il login finisce con `Login OK`. Se fallisce, aspetta un'ora: Garmin limita i tentativi di login per IP. |
| `curl .../healthz` risponde `unauthorized` | Percorso sbagliato (solo `/healthz` è aperto senza token). |
| Claude: *"Unexpected non-whitespace character after JSON"* | Il blocco è stato incollato fuori dalle `{ }` principali di `claude_desktop_config.json`. Verifica il file con un validatore JSON. |
| `garmin-coach` non compare in Impostazioni → Sviluppatore | File di configurazione non valido, o Claude era aperto mentre salvavi. Chiudi Claude (anche dalla tray), correggi, riapri. |
| Server in errore, il log dice che `npx` non si trova | Node.js mancante o installato con Claude aperto. Riavvia Claude, o usa il percorso completo (`C:\\Program Files\\nodejs\\npx.cmd`). |
| Nuovi strumenti non visibili dopo un aggiornamento | Riavvia Claude Desktop e apri una nuova chat. |
| Una modifica al `.env` non ha effetto | Usa `docker compose up -d`, non `restart`. |

---

## Dati, privacy e sicurezza

- Tutti i dati restano in `./data` sul tuo server: database SQLite, FIT originali, token, le tue note.
  `data/` e `.env` sono esclusi da `.gitignore`.
- `.env` contiene la chiave Personal API, e `data/tokens/` il token di accesso e (se attivo) i token del modulo
  community: proteggili come password.
- L'endpoint MCP è HTTP semplice protetto da token: **tienilo sulla rete di casa** (o dietro VPN).
  Non esporre la porta 8765 su internet.
- `query_sql` apre il database in sola lettura. Le uniche scritture possibili per Claude sono le annotazioni
  nell'archivio locale e, con il modulo della community attivo e dopo la tua conferma, gli allenamenti su Garmin Connect.

---

## Limiti e avvertenze

- Il progetto **non è affiliato né approvato da Garmin**.
- La Personal API ufficiale è **in sola lettura** e pensata per l'uso personale con il proprio account.
  Non espone il passo corretto per la pendenza per singolo lap, le scarpe né il VO2max per attività.
- La scrittura usa l'API non ufficiale tramite il modulo della community: Garmin può cambiarla in qualsiasi momento.
  L'archivio locale resta comunque disponibile.
- Allenamenti: per ora solo corsa (niente forza, bici o nuoto).
- Funziona con Claude Desktop, a computer acceso e sulla stessa rete del server.
  L'accesso da remoto (claude.ai web/mobile) richiederebbe HTTPS e un'autenticazione vera: non incluso.
- È solo un progetto personale che ho voluto condividere con la community. Buon divertimento!

---

## Ringraziamenti

Il progetto si basa su questi progetti open source:

| Progetto | Ruolo | Licenza |
|---|---|---|
| [garmin-connect-personal-api-python](https://github.com/garmin/connect-personal-api-python) di Garmin | Client ufficiale della Personal API (sorgente dati in sola lettura) | Apache-2.0 |
| [python-garminconnect](https://github.com/cyberjunky/python-garminconnect) di cyberjunky | Modulo opzionale della community (scrittura) | MIT |
| [fitdecode](https://github.com/polyvertex/fitdecode) di polyvertex | Lettura dei file FIT | MIT |
| [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk) | Server MCP | MIT |
| [Uvicorn](https://github.com/encode/uvicorn) | Server ASGI | BSD-3-Clause |
| [mcp-remote](https://github.com/geelen/mcp-remote) di geelen | Ponte tra Claude Desktop e server MCP remoti | MIT |

Elenco completo, con le dipendenze indirette e le note sui marchi: [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

## Licenza

[MIT](LICENSE)
