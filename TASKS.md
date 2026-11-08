# TASKS — DA-PXREPL

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
- [ ] Da valutare: il riepilogo dice «NON PARTITO» per i dischi saltati dalla catena senza dire perché; «VMID già in uso» non va scritto come «Registrazione VM fallita»
- [x] ~~Difetto nuovo (08/11)~~: 12 gruppi di replica insieme esauriscono il pool SQLAlchemy (5+10): ogni replica tiene una sessione per tutta la durata. 5 gruppi sono morti in background senza riga nel registro, `/run` del backup config ha dato 500, e la registrazione post-sync della VM 117 (job 4) è saltata (`_try_register_vm_after_sync`): verificare la VM 9117 su DTS-PX-04
- [ ] A parte: i job dei dischi secondari (101 disk-2/3/4, 109 disk-2/3, 114 disk-0, 115 disk-1) «NON PARTITO» dal 26-27/10
