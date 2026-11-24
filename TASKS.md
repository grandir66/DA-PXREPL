# TASKS — DA-PXREPL

## 2026-11-24 — Migliorie, 3.26.0 (Riccardo: «puoi procedere con ulteriori punti di miglioramento»)

- [x] Recupero all'avvio delle corse saltate (`scheduler_recupero_avvio`, Impostazioni → Generale → Scheduler): nasce spento
- [x] Cache VM: un nodo che non risponde non svuota più la cache (`get_cluster_resources_esito`)
- [x] `is_online`/`last_check` dei nodi dal giro periodico (non in linea dopo 3 giri muti). I PBS restano fuori: il loro stato lo scrive ancora solo il «Test» a mano
- [x] `update.sh`: ultime 10 copie di database e ambiente, journal a 200 MB. Vale dall'aggiornamento successivo (gira lo script vecchio): le 36 copie di Domarc spariscono al prossimo
- [x] Lint e typecheck del frontend verdi
- [x] Domarc alla 3.26.0 (24/11 17:10, snapshot LXC 332 `pre-pxrepl-3260-20261124`): healthy, nodi con `last_check` di oggi, 84 VM in cache come prima
- [x] DTS alla 3.26.0 (24/11 17:20, ok di Riccardo): snapshot LXC 124 `pre-pxrepl-3260-20261124`, healthy, chiavi del cluster 8 righe
- [x] Recupero all'avvio **acceso sui due siti** (24/11, ok di Riccardo), scritto nel database DOPO il riavvio: vale dal prossimo avvio del servizio, oggi non ha rilanciato niente (a DTS avrebbe fatto partire 12 repliche con 12 giorni di arretrato in orario di lavoro)
- [ ] Snapshot dell'LXC 332 da togliere quando le corse di stanotte sono verdi: `pre-pxrepl-3245-`, `-3250-`, `-3260-20261124`
- [ ] Non fatto, da valutare: ripuntare un job su un'altra VM dall'interfaccia (oggi serve scrivere nel database, come per la 699)

## 2026-11-24 — Richieste di Riccardo per le prossime versioni (da progettare, niente codice ancora)

Riccardo, 24/11: «inviare i log completi e parlati ad un syslog, in particolare a Wazuh»; «risolvere l'opzione di registrazione della VM replicata evitando che il flag di partenza automatica sia attivo»; «risolvere il problema degli uuid duplicati»; «prevedere di ripristinare l'originale dalla replica con l'id e nome originale … il caso di DTS per 3CX che ora lavora con la copia replicata e vorrei ritornare alla copia originale ricostruendo la sequenza»; «aggiungiamo ovviamente il controllo esterno su Zabbix».

Risposte di Riccardo (24/11): 1) a syslog va **tutto il log tecnico**, non solo gli eventi; 2) l'avvio automatico non l'ha visto, «potrebbe esistere come problema (esiste nelle repliche di Veeam)»: basta una guardia; 3) sugli uuid di Domarc decide l'agente → si riallineano le 9 repliche spente su PX-NAS; 4) 3CX DTS: l'originale (103) si è **danneggiato per un salto di corrente**, l'utente ha acceso la replica; si torna alla macchina originale «ma con i dati aggiornati della replica» → il disco della 103 non è buono, ritorno **completo** su dataset nuovo, il vecchio da parte; 5) Zabbix lo configura l'agente su DA-Zabbix, solo per DA-PXREPL.
Ancora da sapere: indirizzo/porta/protocollo del syslog Wazuh per sito; finestra di fermo del centralino DTS; credenziale di DA-Zabbix.

Accessi trovati il 24/11 (Riccardo: «puoi leggere dalla cartella padre», nessun segreto qui): **DA-Zabbix** = `ssh domarc@192.168.4.15` (VM 107 su DA-PX-01, sudo), URL e utente amministratore dell'API in `/etc/zbxwizard/zabbix.env` (`ZBX_URL`, `ZBX_ADMIN_USER`, `ZBX_ADMIN_PASS`), contesto in `~/Progetti/DA-Zabbix/CONTEXT.md`; **DA-WAZUH** = `ssh domarc@192.168.4.19` (VM 444, sudo), contesto e accessi in `~/Progetti/DA-Wazuh/`. Su DA-WAZUH ci sono già ricevitori syslog UDP aperti a 192.168.0.0/16 (3514 per UniFi, 5614), ma per DA-PXREPL servono **porta dedicata e regole**, cioè un modulo di DA-Wazuh (`moduli/`): senza regole le righe arrivano e non producono niente. Esiste anche un Wazuh di DTS (DA-Wazuh `TASKS.md`).

- [~] **Log a syslog/Wazuh** (3.25.0: scheda Impostazioni → Syslog remoto, spento di default; **da accendere** quando Riccardo dà indirizzo e porta di Wazuh per sito e la ricezione è abilitata sul collettore): prima non c'era niente (`logging_config.py` ha solo console, file e un `JSONFormatter`). Da decidere: indirizzo e porta per sito, UDP o TCP, quali eventi «parlati» (job partito/riuscito/fallito, accessi, modifiche, DR)
  - 24/11, lato Wazuh pronto e **non rilasciato**: modulo `da-pxrepl` 1.0.0 in DA-Wazuh (`71e17f1` su `main`, `~/Progetti/DA-Wazuh/moduli/da-pxrepl/`, aperti nel suo `TASKS.md`, sezione del 24/11). Porta **5517 UDP** (innesto `remote-5517`, reti private), regole 100700-100732: INFO/DEBUG solo archivio, WARNING 4, ERROR 8, CRITICAL 12, allarme su replica fallita, «Replica in ritardo», «UUID SMBIOS duplicati», «Repliche con avvio automatico attivo», scheduler bloccato, `Proxmox login failed` (raffica). Provato con `wazuh-logtest` sulla VM di prova (192.168.4.193): 14 righe campione vere su 14. Da fare, con l'ok di Riccardo: rilascio di DA-Wazuh su DA-WAZUH e «Applica» del modulo; poi qui, Domarc (192.168.4.199): Impostazioni → Syslog remoto = `192.168.4.19`, porta `5517`, `UDP`; DTS (172.16.1.145): `172.16.1.10`, `5517`, `UDP` dopo il rilascio sul Wazuh di DTS (cliente: con conferma).
- [x] **Avvio automatico della replica** (3.25.0: guardia ogni 6 h che avvisa, `services/repliche_onboot.py`): dalla 3.22.0 la registrazione scrive `onboot 0` (`replica_identity.py`). Misurato il 24/11: nessuna replica con `onboot: 1` né a DTS (12 repliche) né su PX-NAS (10). Capire da Riccardo dove l'ha visto attivo
- [x] **UUID duplicati** (3.25.0: «Riallinea identità»; 24/11 Domarc alla 3.25.0, snapshot LXC 332 `pre-pxrepl-3250-20261124`, riallineate le 9 repliche su PX-NAS: 2001, 20002, 20003, 20009, 22003, 22007, 22008, 22011, 35456; copia dei `.conf` di prima in `/root/dapx-bak-20261124` su PX-NAS. Resta la 20005, vecchia replica del firewall, con l'uuid della 699: sparisce quando si toglie): a Domarc le 9 repliche su PX-NAS, registrate prima della 3.22.0, hanno ancora lo stesso uuid della sorgente (401, 402, 406, 423, 432, 444, 455, 664, 699). Manca un'azione «riallinea identità» per le repliche già registrate. A DTS l'unica coppia è 103/9103, cioè il caso 3CX qui sotto
- [ ] **Ritorno dalla replica all'originale (failback)**: oggi c'è solo «Attiva DR» (`routers/vms.py`), niente strada di ritorno. Caso DTS: 9103 «3CX-V20-replica» accesa su DTS-PX-04 con l'uuid originale, 103 «3CX-V20» spenta su DTS-PX-UP; è anche il motivo del job 2 che fallisce dal 12/11. Sequenza da progettare: fermo della replica, sincronizzazione inversa 9103→103, riaccensione della 103 con id, nome e uuid originali, replica rimessa nel verso giusto
- [x] DTS alla 3.25.0 (24/11 15:22, ok di Riccardo): snapshot LXC 124 `pre-pxrepl-3250-20261124` su DTS-PX-04, health 3.25.0 healthy, chiavi del cluster 8 righe prima e dopo. L'LXC 124 ha ora 7 snapshot: i vecchi si tolgono quando le repliche sono tornate verdi
- [ ] Frontend: `npm run lint` (1 errore in `services/clusters.ts`) e `npm run build:check` (2 errori in `HostBackupView.vue:351`) sono rossi da prima della 3.25.0; `npm run build` passa
- [x] **Controllo esterno su Zabbix** (DA-Zabbix): fatto il 24/11. Template `DATIA DA-PXREPL by HTTP` e host `dapx-domarc` (dal server) e `dapx-dts` (da `proxy-dts`), item con valori veri alle 16:25; trigger: non risponde da 10 min, stato non `healthy`, nessuna corsa riuscita da 36 ore, repliche fallite. Già accesi: repliche fallite = 1 su tutti e due, e su DTS 282 ore dall'ultima corsa riuscita (si chiude alla prima replica riuscita). Snapshot VM 107 `pre-pxrepl-zabbix-20261124` su DA-PX-01. Dettaglio e aperti in `~/Progetti/DA-Zabbix/TASKS.md`, sezione del 24/11.

## 2026-11-24 — Verifica delle due installazioni (Domarc 3.21.3, DTS 3.24.4)

Riccardo: «analizza il progetto e verifichiamo le due implementazioni, una in Domarc e una in DTS, per valutarne errori e miglioramenti». Sola lettura sul live, 24/11 ore 14:05 (diagnostica via `pct exec`, DB aperto in sola lettura).

DTS (LXC 124 su DTS-PX-04):
- [ ] **LXC 124 spento dal 12/11 23:36 al 24/11 13:46**: DTS-PX-04 si è riavviato il 12/11 alle 23:38 e il container non è ripartito (oggi l'ha avviato root@pam a mano; `onboot: 1` oggi c'è). 12 giorni senza repliche né backup config, ultima snapshot sul pool 12/11 22:02. Nessuno è stato avvisato: chi avvisa è il container stesso. Alla ripartenza è uscito l'alert «12 gruppi in ritardo»; lo scheduler non recupera le corse perse, ripartono al prossimo orario
- [ ] Controllo dal di fuori (Zabbix su `/api/health` + età dell'ultima corsa): manca in tutti e due i siti
- [ ] Job 2 VM-103: la VM sta su DTS-PX-04 che è la destinazione, fallisce dal 12/11: decidere se spostare la VM o rivedere il job
- [ ] Destinatari notifiche `…@dts-automotime.it` (il mittente è `dts-automotive.com`): refuso? `smtp_host` ha uno spazio in coda
- [ ] DTS2-PBS (192.168.16.99) non risponde sulla 22 a ogni giro; UUID SMBIOS duplicati: 1 coppia; tre job «Backup Config» con lo stesso nome
- [ ] Journal del container: 502 MB, nessun tetto

Domarc (LXC 332 su DA-PX-04):
- [x] (24/11: aggiornata alla 3.24.5, snapshot LXC 332 `pre-pxrepl-3245-20261124` su DA-PX-04, health 3.24.5 healthy, chiavi del cluster 10 righe prima e dopo) Ancora 3.21.3: mancano la correzione delle chiavi del cluster (3.24.2), il tetto alle repliche (3.24.3), il battito dello scheduler in `/api/health`. Nessuno snapshot del container
- [x] Job 6: Riccardo, 24/11: «la 666 era il vecchio firewall che ora ha cambiato ID e va replicato quello». È la 699 Stormshield-SS-EVA2-OK su DA-PX-03: job 6 ripuntato a mano nel DB su `zfs/vm-699-disk-0` → `ZFS-LARGE/replica/vm-699-disk-0`, VMID di destinazione 20699. Prima corsa (completa, 10 GB) stanotte alle 00:00: **esito da leggere**
- [ ] Su PX-NAS resta la replica vecchia: VM 20005 e `ZFS-LARGE/replica/vm-666-disk-0` (1,85 GB, ultima snapshot 05/10). Si toglie solo se lo dice Riccardo
- [ ] Job 15 VM-402 senza orario, fermo dal 17/07: tenerlo o toglierlo?
- [x] (3.24.5: uscita 1 di tar = avviso, errore col codice e il messaggio; causa probabile, non provata: file di /etc/pve cambiato durante la lettura. Leggere le prossime corse) Backup Config DA-PX-04: 3 falliti in 14 giorni con «Errore creazione backup:» vuoto (`host_backup_service.py:255`, stderr e stdout vuoti)
- [ ] 36 copie di `dapx.db.backup-*` e 15+ `.env.pre-update-*` mai ruotate; resti: `/opt/dapx-unified/_archive`, `get_valid_key.py`, `/var/log/dapx-backandrepl`

- [x] DTS alla 3.24.5 (24/11 14:32, ok di Riccardo): snapshot LXC 124 `pre-pxrepl-3245-20261124` su DTS-PX-04, health 3.24.5 healthy, chiavi del cluster 8 righe prima e dopo
- [ ] DTS: leggere le repliche che ripartono da stasera (ultima riuscita 12/11 21:02) e togliere poi gli snapshot vecchi dell'LXC 124 (ne ha 6)
- [ ] `cache_service`: se il nodo non risponde l'elenco è vuoto e le VM in cache vengono cancellate (ripiego muto, visto leggendo il codice il 24/11, non corretto)

Codice (valgono per tutti e due):
- [x] (3.24.5) `cleanup_old_logs` cancella `audit_logs WHERE timestamp`, la colonna è `created_at`: la pulizia dell'audit non ha mai funzionato (`update_db_schema.py`)
- [x] (3.24.5) `cache_service.refresh_node_vms` tratta i PBS come PVE: ~1900 avvisi a settimana a Domarc
- [x] (3.24.5: lo scrive il giro della cache quando il nodo risponde con dei dati; `is_online` resta quello del test a mano) `nodes.last_check` non lo scriveva nessuno (aprile-giugno a Domarc, NULL a DTS): `is_online` non dice niente
- [x] (3.24.5, prova `test_percorso_illeggibile_e_404_non_500`) Una scansione (percorsi `/../etc/passwd`, byte non validi) dà 500 con traceback invece di 404: 36 a settimana a Domarc (visto su 3.21.3, da riprovare sulla 3.24.4)
- [x] (3.24.5: campo `jobs`, lo stato non cambia) `/api/health` dice «healthy» anche con job falliti da 50 giorni: aggiungere il conto dei job in ritardo/falliti

## 2026-11-08 — DTS: repliche e backup config falliti (chiavi ssh sparite)

Diagnosi (08/11, sola lettura sul live):
- Il 06/11 alle 07:25 `/etc/pve/priv/authorized_keys` del cluster DTS è stato riscritto: restano 5 righe
  (wizard@da-zabbix, dapx-executor .141/.142, root@DTS-PX-UP, root@DTS-PX-DOWN). Mancano
  `dapx-unified@dapx-unified` (LXC 124, l'orchestratore) e `root@DTS-PX-04`.
- Da allora l'LXC 124 riceve «Permission denied» da tutti e tre i nodi. L'app lo traduce in «Dataset sorgente non trovato»
  (syncoid) e in «Nessun file di configurazione trovato» (backup config): ripiego muto.
- Causa probabile (non provata dal journal): `_ensure_executor_authorized` in `backend/services/syncoid_service.py`
  riscrive l'intero file a ogni corsa (`awk > tmp; cat tmp > authorized_keys`) con un tmp dal nome fisso e senza lock.
  Due job contemporanei verso DTS-PX-04 → uno legge il file mentre l'altro lo tronca → righe perse sul file del cluster.

- [x] Riparazione sul live (08/11): copia `/root/authorized_keys.bak-20261108-144556` su DTS-PX-04, reinserite le chiavi di dts-repl e DTS-PX-04; da LXC 124 ssh e `zfs list` ok su UP/DOWN
- [x] Correzione del codice: v3.24.2, prova nuova `test_chiavi_cluster_dts_2026_11_06.py` (4 rosse prima, suite 512 verdi dopo)
- [x] Rilascio v3.24.2 e DTS aggiornato (snapshot LXC 124 `pre-pxrepl-3242-20261108` su DTS-PX-04, /api/health 3.24.2 healthy)
- [ ] Leggere il riepilogo DAPX di domani 09:00: repliche e backup config di UP/DOWN verdi
- [x] Job falliti rilanciati a mano l'08/11 alle 15:00: 13 dischi ok (101 tutti, 103, 109 tutti, 115 tutti, 117, 126, 130) e backup config UP/DOWN ok; 104/111/112/114/122 rilanciati alle ~15:25 (esito da leggere)
- [x] Corretto in v3.24.3 (tetto `DAPX_MAX_REPLICHE`=4, gruppo interrotto nel log), DTS aggiornato alle ~16:10 (snapshot LXC 124 `pre-pxrepl-3243-20261108`). VM 9117 verificata: config e snapshot del 08/11 15:01 ok. Esiti: 104, 111, 112, 122, 114 disk-1 ok
- [x] VM 114 (08/11): 9114 registrata con i due dischi («VMID già in uso» = già registrata, messaggio fuorviante); disk-0 fermo dal 27/10 perché la catena del gruppo si ferma al primo disco fallito, rilanciato: success, snapshot 16:27
- [x] v3.24.4 (08/11): «Saltato: disco precedente fallito» e «VM già registrata» nel riepilogo; DTS aggiornato (snapshot LXC 124 `pre-pxrepl-3244-20261108`, health 3.24.4)
- [x] ~~Difetto nuovo (08/11)~~: 12 gruppi di replica insieme esauriscono il pool SQLAlchemy (5+10): ogni replica tiene una sessione per tutta la durata. 5 gruppi sono morti in background senza riga nel registro, `/run` del backup config ha dato 500, e la registrazione post-sync della VM 117 (job 4) è saltata (`_try_register_vm_after_sync`): verificare la VM 9117 su DTS-PX-04
- [ ] A parte: i job dei dischi secondari (101 disk-2/3/4, 109 disk-2/3, 114 disk-0, 115 disk-1) «NON PARTITO» dal 26-27/10
