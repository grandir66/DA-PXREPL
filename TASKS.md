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

- [ ] Riparazione sul live (sistema del cliente: serve l'ok di Riccardo): copia del file, reinserire le due chiavi, provare un job
- [ ] Correzione del codice: niente riscrittura se la riga c'è già, `flock` + tmp univoco, errore ssh detto come errore ssh
- [ ] Rilascio da `main` e aggiornamento di DTS dal bottone Aggiorna
- [ ] A parte: i job dei dischi secondari (101 disk-2/3/4, 109 disk-2/3, 114 disk-0, 115 disk-1) «NON PARTITO» dal 26-27/10
