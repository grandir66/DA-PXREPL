# Vita dello scheduler

> Dalla 3.24.0. Codice: `SchedulerService._scheduler_loop`, `_esegui_check`,
> `_battito` in `backend/services/scheduler.py`; `SSHService._arma_keepalive`
> e `_attendi_esito` in `backend/services/ssh_service.py`; `/api/health`.

## Il fatto

dts-repl, 21 settembre 2026, 15:52:04: l'ultima riga di journal prima del
riavvio del 22. Il loop dello scheduler era entrato in `refresh_all_nodes →
update_host_details` — un SSH a un nodo durante una tempesta L2, col nodo
appena spento col tasto — e non ne è più uscito: la connessione era mezza
morta, `recv_exit_status()` di paramiko non ha timeout, e il loop esegue i
check in sequenza con `await`. **Nove ore** senza corse (18, 19, 21, 22),
senza cache VM, senza errori, senza alert; `/api/health` diceva `scheduler:
running`, perché era un flag e non una prova di vita.

## Cosa fa adesso

**Ogni check ha un tetto** (`SchedulerService.CHECKS`: jobs 120 s, cache VM e
host info 600 s, gli altri 120-300 s). Se non finisce, `asyncio.wait_for` lo
abbandona, si logga `ERROR` con il nome del check e il giro prosegue con il
successivo: un nodo che non risponde non ferma le repliche degli altri. Due
scadenze di fila dello stesso check mandano un `warning` sul canale delle
notifiche («Scheduler: check «cache_vm» bloccato»), al massimo uno al giorno
per check; un check che torna a finire azzera il conteggio.

**Il battito.** A fine giro `last_tick` in memoria e `SystemConfig
scheduler_last_tick` nel DB. `/api/health` lo espone (`scheduler_last_tick`)
e, se ha più di dieci minuti, risponde **503** con `status: degraded` e
`checks.scheduler: "stale (N min senza giro)"` — è quello che un monitoraggio
esterno (Zabbix è già sul cluster) deve leggere.

**Le connessioni SSH non restano appese.** Al connect si arma il keepalive di
paramiko (30 s) e quello TCP del kernel (`SO_KEEPALIVE`, `TCP_USER_TIMEOUT`
120 s, dove esistono): una connessione senza più nessuno dall'altra parte
viene chiusa dal trasporto in ~2 minuti. L'attesa dell'esito di un comando
aspetta a passi di 30 s e a ogni passo controlla che il trasporto sia vivo;
se è caduto, il comando torna con `ConnectionError` e `SSHResult` di
trasporto (`exit_code -1`). Un comando lungo e vivo — una replica di ore —
non viene toccato: il tetto è sulla vita della connessione, non sulla durata.

## Cosa NON fa

Non uccide il thread rimasto appeso quando un check viene abbandonato: quel
thread muore quando il TCP si arrende (con il keepalive, minuti; senza, era
mai). Se un nodo sparisce per ore, i thread dell'executor che gli erano
dedicati si liberano man mano; il loop intanto lavora.

## Prove

`backend/tests/test_scheduler_vita.py` (check abbandonato e giro che
prosegue, avviso dopo due scadenze e cooldown, azzeramento, errore che non
ferma, health stale/running), `backend/tests/test_ssh_connessione_morta.py`
(keepalive armato al connect, esito che alza se il trasporto muore, comando
lungo e vivo che aspetta, `execute` che torna con errore di trasporto).
