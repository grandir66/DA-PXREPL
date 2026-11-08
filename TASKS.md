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
- [ ] A parte: i job dei dischi secondari (101 disk-2/3/4, 109 disk-2/3, 114 disk-0, 115 disk-1) «NON PARTITO» dal 26-27/10
