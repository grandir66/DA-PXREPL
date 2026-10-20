# CONTEXT.md — DA-PXREPL

> Bozza del 20/10/2026 ricavata dalla scheda del censimento (`docs/scheda-mappa.md`)
> nel lavoro `riorg-contesto-agenti`: chi lavora qui la completa sul modello
> `~/Progetti/_template/CONTEXT-TEMPLATE.md` (architettura, trappole, decisioni).

## 1. Cos'è e perché esiste

cruscotto backup/replica Proxmox (ZFS Sanoid/Syncoid, PBS)

Otto tipologie di attività sotto un solo cruscotto: replica VM, snapshot,
replica dati, sync NAS, backup e recovery PBS, backup host, migrazione live.

**3.24.1 rilasciata il 6 ottobre**: destinatario predefinito delle notifiche
`proxmox@domarc.it` (solo dove è vuoto). In esercizio: DTS alla 3.24.0 dal 22
settembre (scheduler con battito, il job segue la VM), Domarc ancora 3.21.3.

**Trappola corrente**: il rilascio si fa solo da `main` e finisce alla
release di GitHub (`.claude/rules/rilascio.md`): l'8 settembre una versione
nata su un ramo 35 commit indietro non arrivò mai su `main`.

## 2. Stato — dal censimento, 2026-10-20

- Stato: **manutenzione**.
- Prossimo passo: portare DTS e Domarc alla 3.24.1 dal bottone Aggiorna, poi leggere le corse delle 02:00 e /api/health (battito)
