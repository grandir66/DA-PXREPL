# Il job segue la VM

> Dalla 3.23.0. Vale per i job di replica VM (`syncoid`, `pve_native`,
> `btrfs`) con un `vm_id`. Codice: `backend/services/vm_locator.py`, innesto
> in `execute_sync_job_task` e nella registrazione post-sync.

## Il problema

Un job di replica nasce con il nodo sorgente fissato al giorno in cui è stato
creato. In un cluster Proxmox la VM **si sposta** — migrazione a mano per una
manutenzione, HA che la riavvia altrove quando un nodo cade — e fino alla
3.22 il job continuava a partire dal nodo vecchio, cadendo sul pre-check
«dataset does not exist» senza dire perché. Chi legge il log vede un errore
ZFS, non «la VM è altrove».

## Cosa fa adesso, a ogni corsa

Prima di partire il job chiede al cluster dove sta la VM (`pvesh get
/cluster/resources`, una chiamata per cluster al minuto: i dischi dello stesso
gruppo la condividono). Quattro esiti, tenuti distinti:

| Esito | Quando | Cosa succede |
|---|---|---|
| **uguale** | la VM sta sul nodo registrato | come sempre |
| **spostata** | sta su un altro nodo **censito** in DA-PXREPL, raggiungibile, con il dataset sorgente presente | si esegue da lì; `source_node_id` viene aggiornato su tutti i dischi del gruppo; il log lo dice: «VM 101 trovata su px-03 (era registrata su px-01): eseguo da px-03» |
| **non so** | il cluster non risponde, o la VM non è in elenco (nodo standalone, VM cancellata) | si usa il nodo registrato e lo si scrive nel log — «non so» non è «no» |
| **rifiutata** | sta su un nodo **non censito**, o senza il dataset, o sul nodo di **destinazione** del job | la corsa **non parte**: JobLog `failed` con il motivo, contatori e notifica come per un fallimento; il nodo registrato non si tocca |

Se il nodo registrato è quello morto (è il caso dell'HA), la mappa si chiede
a un altro nodo censito — e vale solo se elenca il nodo registrato fra i
membri: una mappa di un altro cluster non viene scambiata per la sua.

«Carte in regola» del nodo nuovo, in ordine: censito come nodo PVE attivo
(con lo **stesso nome** del nodo Proxmox, la regola già in vigore per la
cache VM); raggiungibile; `zfs list` del dataset sorgente riesce. La chiave
dell'executor sulla destinazione la installa `run_sync` da sé a ogni corsa,
quindi un nodo nuovo funziona senza altro.

## Dopo una migrazione: replica completa

Con una migrazione **offline** Proxmox trasferisce i volumi ZFS con i loro
snapshot: l'incrementale continua. Con una migrazione **live** i dischi sono
copiati con drive-mirror, **senza** gli snapshot ZFS: sul nodo nuovo syncoid
non trova snapshot in comune con la destinazione e si rifiuta:

```
CRITICAL ERROR: Target ZFS/replica/vm-101-disk-0 exists but has no snapshots matching with rpool/data/vm-101-disk-0!
Cowardly refusing to destroy your existing target.
```

Serve una replica completa (la destinazione ricreata da zero). La scelta,
presa il 2026-09-22: **di default la corsa fallisce e lo dice**. Una
manutenzione che migra dieci VM non deve produrre dieci repliche complete
contemporanee sul link.

- Il log e la notifica portano il motivo in chiaro (`[REPLICA-COMPLETA] VM
  migrata su px-03: la destinazione non ha snapshot in comune…`) e il job
  viene segnato (`richiede_replica_completa`).
- Nella pagina Repliche il gruppo mostra il badge **«replica completa
  richiesta»**; premendo **Esegui** compare una conferma: «Replica completa»
  lancia la corsa con `--force-delete` **per quella volta sola**
  (`POST /api/sync-jobs/vm-group/{gruppo}/run?replica_completa=true`, o
  `/api/sync-jobs/{id}/run?replica_completa=true`). Alla corsa riuscita il
  segno si spegne da solo.
- Chi vuole l'automatismo lo accende **per job**: «Dopo una migrazione della
  VM riparti da solo con replica completa» (`resync_dopo_migrazione`, nel
  modale del job, sezione syncoid). Agisce solo sulla corsa in cui la VM
  risulta spostata.

`--force-delete` ricrea la destinazione **solo** se non ha snapshot in
comune: se gli snapshot ci sono (migrazione offline) l'incrementale prosegue
normalmente anche con il flag.

## Cosa resta da fare a mano

- **Snapshot sanoid**: la configurazione sanoid del dataset vive sul nodo
  vecchio. La replica funziona lo stesso (syncoid crea i suoi sync-snapshot),
  ma la retention locale degli snapshot sul nodo nuovo non c'è finché non si
  riconfigura. Passo successivo previsto: «sanoid segue la VM».
- **Nodo non censito**: se la VM finisce su un nodo che DA-PXREPL non
  conosce, il job lo dice e si ferma. Censire il nodo (stesso nome Proxmox,
  chiave SSH) o riportare la VM.

## Prove

`backend/tests/test_vm_locator.py` (i quattro esiti, la mappa dall'altro
nodo, la cache, la persistenza sul gruppo), `backend/tests/test_job_segue_la_vm.py`
(la corsa parte dal nodo risolto, rifiuta prima di partire, traduce il
rifiuto di syncoid, la corsa una tantum, il flag per job, le rotte).
