# Design — Default SMTP domarc e identificazione cliente nelle notifiche

Data: 2026-07-21
Stato: approvato (design discusso e validato con l'utente)

## Obiettivo

Ogni installazione DAPX deve uscire dall'installazione con il server SMTP domarc
già configurato come default (credenziale cifrata nel DB), e ogni email di
notifica deve identificare il cliente nell'oggetto nel formato `CODCLI - NOMECLI`.

## Vincoli

- Il repo GitHub è **pubblico**: la password SMTP non deve mai comparire in git
  (né in chiaro, né offuscata). Nel codice possono stare solo host, porta e utente.
- `DAPX_SECRET_KEY` è generata casualmente da `install.sh` per ogni installazione:
  la cifratura della password può avvenire solo sul target, al primo avvio.
- Le configurazioni esistenti non vanno mai sovrascritte dal seed dei default.
- Nessuna password nei log, nelle risposte API o nella documentazione.

## Requisiti

1. Default SMTP precompilati a ogni nuova installazione:
   - server: `esva.domarc.it`, porta `25`, utente `smtp.domarc`
   - TLS: STARTTLS opportunistico (il server lo espone come opzionale)
   - password: fornita al deploy fuori da git, cifrata nel DB al primo avvio
2. Password SMTP cifrata at-rest nel DB (oggi è salvata in chiaro nonostante il
   commento `# Encrypted` sul modello).
3. Mittente per installazione: campo `smtp_from` esistente; se vuoto viene
   derivato `dapx-<codcli>@domarc.it`, fallback `dapx@domarc.it` se manca codcli.
4. Destinatari per installazione (una casella domarc + una del cliente), campo
   esistente `smtp_to` (lista separata da virgola). Nessun default committato.
5. Oggetto email: `CODCLI - NOMECLI — <oggetto>` in **tutte** le email, inclusi i
   job con oggetto personalizzato (`notify_subject`) e le email di test.
6. `smtp_enabled` resta `False` di default: con destinatari vuoti ogni job
   genererebbe solo notifiche fallite. L'admin lo abilita quando compila
   destinatari e dati cliente.

## Architettura

### 1. Helper cifratura generico — `backend/services/secrets.py` (nuovo)

Generalizza la logica Fernet oggi in
`backend/services/file_replication/endpoint_crypto.py`:

- `encrypt_secret(plain: str) -> str` e `decrypt_secret(token: str) -> str`,
  chiave derivata SHA-256 da `DAPX_SECRET_KEY` (identica all'attuale).
- `is_encrypted(value: str) -> bool`: tenta la decifratura, `False` su
  `InvalidToken` — usato dalla migrazione idempotente.
- `endpoint_crypto.py` diventa un wrapper che importa da `secrets.py`
  (pattern wrapper: nessuna modifica ai consumatori esistenti, stessi token
  compatibili perché chiave e algoritmo non cambiano).

### 2. Cifratura at-rest della password SMTP

- `PUT /api/settings/notifications` (`backend/routers/settings.py`): se
  `smtp_password` è presente e non vuota nel payload, viene cifrata prima del
  salvataggio.
- `notification_service._configure_email_service` e l'endpoint di test
  `POST /api/settings/notifications/test` decifrano prima di passare la
  password a `email_service`.
- **Migrazione idempotente allo startup** (in `update_db_schema.py`, eseguito
  sia dal lifespan sia da `update.sh`): se `smtp_password` è valorizzata ma non
  è un token Fernet valido, viene considerata in chiaro e cifrata sul posto.
  Protegge le installazioni già configurate (.199, .145).
- La risposta `GET /api/settings/notifications` continua a NON esporre la
  password (già così oggi).

### 3. Seed dei default al primo avvio

In `init_default_config()` (`backend/database.py`), solo quando
`NotificationConfig.smtp_host` è vuoto (mai su config già toccate):

- `smtp_host = "esva.domarc.it"`, `smtp_port = 25`, `smtp_user = "smtp.domarc"`,
  `smtp_tls = True` (con la nuova semantica opportunistica, v. §5)
- password: se l'env `DAPX_SMTP_DEFAULT_PASSWORD` è presente e
  `smtp_password` è vuota → cifrata e salvata. Il seed della password è
  indipendente dal seed dell'host (gestisce install dove l'env arriva dopo).
- `smtp_enabled` resta `False` (v. Requisito 6).

### 4. Consegna della password al deploy — `install.sh`

- Nuovo parametro opzionale: `install.sh` accetta sia il flag `--smtp-password`
  sia l'env `DAPX_SMTP_PASSWORD` (il flag ha precedenza). Nessun prompt
  interattivo, per non rompere le install non presidiate.
- Se fornita, `install.sh` aggiunge `DAPX_SMTP_DEFAULT_PASSWORD=<valore>` a
  `/etc/dapx-unified/dapx-unified.env` (file già usato dal systemd unit via
  `EnvironmentFile`), con permessi `600 root:root`.
- La sorgente del valore è il vault locale dell'operatore, fuori da git.
- `update.sh` non richiede modifiche: l'env file persiste agli update.
- Installazioni esistenti: due strade equivalenti, (a) aggiungere la riga
  all'env file e riavviare il servizio, (b) inserire la password nella tab
  Notifiche della UI. Documentate nel README/CHANGELOG.

### 5. STARTTLS opportunistico — `backend/services/email_service.py`

Oggi `use_tls=True` su porta ≠465 forza STARTTLS e fallisce se il server non lo
espone. Nuova semantica di `smtp_tls=True`: dopo `EHLO`, se il server annuncia
`STARTTLS` lo si usa, altrimenti si prosegue in chiaro (coerente con
"SSL: optional" del server domarc). `smtp_tls=False` resta "mai TLS".
Porta 465 resta SSL diretto.

### 6. Identificazione cliente

- Due nuove colonne su `NotificationConfig` (`backend/database.py`):
  `client_code` (String 50) e `client_name` (String 255), nullable.
  Aggiunte anche in `update_db_schema.py` via `_ensure_column`.
- Esposte in `NotificationConfigUpdate` / `NotificationConfigResponse`
  (`backend/routers/settings.py`) e come due campi nella tab Notifiche del
  frontend (stessi componenti form esistenti della tab).
- `EmailService.configure()` riceve `client_code` e `client_name`;
  `send_email()` costruisce l'oggetto: se entrambi valorizzati →
  `"{client_code} - {client_name} — {subject_prefix} {subject}"`, altrimenti
  comportamento attuale (`"{subject_prefix} {subject}"`). Essendo in
  `send_email()`, vale per notifiche job, oggetti personalizzati e email di test.
- Mittente: se `smtp_from` è vuoto, `configure()` deriva
  `dapx-{client_code}@domarc.it` (minuscolo, senza spazi) o `dapx@domarc.it`
  se `client_code` è assente.

## Gestione errori

- `DAPX_SECRET_KEY` assente: `secrets.py` solleva `RuntimeError` (come oggi
  `endpoint_crypto`). La migrazione allo startup la intercetta, logga un
  warning e lascia il valore invariato (non blocca l'avvio del backend).
- Password non decifrabile al momento dell'invio (es. `DAPX_SECRET_KEY`
  cambiata): la notifica fallisce con messaggio chiaro nel log, senza
  esporre il token.
- Nessun valore di password mai loggato, né in chiaro né cifrato.

## Testing

- `secrets.py`: roundtrip encrypt/decrypt, `is_encrypted` su token valido /
  stringa in chiaro / stringa vuota; compatibilità token con `endpoint_crypto`.
- Migrazione: DB con password in chiaro → cifrata; DB con password già cifrata
  → invariata (idempotenza); DB senza password → no-op.
- Seed: DB nuovo → default presenti; DB con `smtp_host` già valorizzato →
  invariato; env password presente/assente.
- `PUT /notifications`: la password arriva cifrata nel DB; update senza campo
  password non tocca il valore esistente.
- Oggetto: con e senza codcli/nomecli, con `notify_subject` personalizzato.
- Mittente derivato: con codcli, senza codcli, con `smtp_from` esplicito.
- Test esistenti (`test_settings.py`, `test_endpoint_crypto.py`) verdi.

## Fuori scope

- Nessun cambiamento a webhook/Telegram.
- Nessuna rotazione automatica della `DAPX_SECRET_KEY`.
- Il branch `feature/nas-sync-v2` (in lavorazione via Cursor) erediterà queste
  modifiche al merge; possibili conflitti minori su `notification_service.py`,
  `settings.py`, `database.py` — da segnalare al momento del merge.
- Rilascio: bump versione (5 file), rebuild `frontend/dist`, CHANGELOG, tag e
  GitHub Release seguono la procedura standard del repo al momento del rilascio.
