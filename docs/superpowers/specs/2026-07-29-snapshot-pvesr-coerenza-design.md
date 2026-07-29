# Convivenza Snapshot VM ↔ replica pvesr — strategia coerente

> Design approvato dall'utente il 2026-07-29. Contesto: cliente DTS con cluster PVE
> a 3 nodi (DTS-PX-UP / DTS-PX-DOWN / DTS-PX-04) dove **tutte** le VM di produzione
> sono replicate via **pvesr**, e **PBS è troppo lento** per un ripristino veloce "a ieri".
> Priorità di progetto: **non rompere nulla**.

## Problema

Il modulo "Snapshot VM" di dapx crea snapshot ZFS (retention + rollback). Su VM con
replica **pvesr** l'unico attrito reale è il **rollback**: ZFS distrugge gli snapshot
più recenti (incluso il "base" di pvesr) → la replica va rifatta. Il wizard oggi mostra
un avviso generico e allarmante ("pvesr può rimuovere snapshot non suoi") **a ogni run**,
poco accurato e rumoroso quando *tutte* le VM sono replicate.

## Verifica empirica (2026-07-29, sul cluster cliente)

- **Gli snapshot utente SOPRAVVIVONO a pvesr**: due snapshot creati su CT124 (guest
  pvesr-replicato) giorni prima esistono ancora → pvesr **non** cancella gli snapshot utente.
- **Replica DR di produzione SANA**: i 14 job pvesr delle VM di produzione hanno
  `last_sync` recente e 0 fallimenti.
- **Isolato**: solo `124-0` (il container dapx) è rotto (SSH verso la rete di replica di
  DTS-PX-DOWN fallisce) — irrilevante per il design, da trattare separatamente.

## Strategia coerente a 3 livelli (ogni scopo → strumento giusto)

| Esigenza | Strumento | Ruolo |
|---|---|---|
| **Recovery veloce recente** ("torna a ieri / ultimi N giorni" in minuti) | **Snapshot ZFS** (dapx) | rollback ~istantaneo; retention breve (es. 3–7) |
| **Disaster recovery** (nodo guasto) | **pvesr** (attivo, sano) | copia recente su altro nodo |
| **Archivio / offsite / lungo termine** | **PBS** (attivo) | conservazione, non recovery veloce |

## Design delle modifiche dapx

### 1. Rollback + resync pvesr automatico (feature principale)
Quando si fa rollback di uno snapshot su una VM con pvesr attivo:
1. dapx esegue il rollback (`qm/pct rollback`, endpoint esistente).
2. dapx rileva i job pvesr del guest (`pvesh get /cluster/replication`, filtrando per `guest`).
3. dapx innesca **subito** un run di ciascun job (`pvesr run <jobid>` sul nodo sorgente) →
   la replica fa il full resync immediato (invece di aspettare il prossimo slot), riportando
   valida la DR con RPO minimo.
4. Esito (rollback + resync avviato/riuscito/fallito) riportato in UI/log.
- **Non-bloccante degradato**: se il resync non parte, si logga un warning con la procedura
  manuale; il rollback resta comunque eseguito (il dato è ripristinato).

### 2. Warning pvesr riformulato (accurato + una volta)
- Testo attuale ("pvesr può rimuovere snapshot non suoi") → **rimosso** (impreciso).
- Nuovo messaggio, mostrato **una volta nel wizard** (non a ogni run): *"N VM hanno replica
  pvesr attiva: un eventuale rollback rifà la replica (resync automatico)."*
- In `execution.py`: il warning per-run resta solo se il resync automatico fallisce.

### 3. Retention compatibile con pvesr (già così, da documentare)
- `select_prunable` pota **solo** gli snapshot `auto<label>_*` del modulo, **mai** i
  `__replicate_*` di pvesr → nessun conflitto con il "base" della replica. Confermato dal design esistente.

### 4. Guida operativa (docs)
- Breve pagina che descrive la strategia a 3 livelli e "quale strumento per quale recovery",
  così la scelta resta documentata per il cliente/operatori.

## Non-goal / fuori scope
- Riparare la replica rotta di CT124 (issue infrastrutturale separata; da valutare a parte).
- Retention lunga via snapshot (è compito di PBS).
- Cambiare pvesr o PBS.

## Rischi
- `pvesr run` post-rollback richiede SSH al nodo sorgente (infrastruttura già usata da dapx).
- Il primo resync post-rollback è **full** (più lungo): atteso e comunicato in UI.
- Rilevamento job pvesr per guest: usare `/cluster/replication` (già usato in `pve_sr_discovery`).

## Verifica end-to-end (a implementazione fatta, su .199 poi cliente)
- Unit: rilevamento job pvesr per un guest; il rollback compone rollback→`pvesr run`.
- Lab: su una VM di test con pvesr, snapshot → rollback via dapx → verifica che la replica
  riparta e torni `last_sync` recente / fail_count 0.
- Warning: il wizard mostra il messaggio una sola volta; nessun avviso per-run se il resync va.
