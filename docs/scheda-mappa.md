---
badge: Vivo
tono: ok
famiglia: 01-nucleo
ordine: 100
stato: cantiere
prossimo: provare su un impianto vero il riepilogo giornaliero rifatto, poi rilasciare
---
cruscotto backup/replica Proxmox (ZFS Sanoid/Syncoid, PBS)

Otto tipologie di attività sotto un solo cruscotto: replica VM, snapshot,
replica dati, sync NAS, backup e recovery PBS, backup host, migrazione live.

**Trappola corrente**: il repo ha **tre worktree**, e l'8 settembre ci si è
messi a lavorare per sbaglio su un ramo 35 commit indietro rispetto a `main`.
Prima di toccare il codice: `git log --oneline -1` e `version.json`.
