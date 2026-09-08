---
badge: Vivo
tono: ok
famiglia: 01-nucleo
ordine: 100
stato: manutenzione
prossimo: guardare il riepilogo di domattina, il primo con la veste nuova in esercizio
---
cruscotto backup/replica Proxmox (ZFS Sanoid/Syncoid, PBS)

Otto tipologie di attività sotto un solo cruscotto: replica VM, snapshot,
replica dati, sync NAS, backup e recovery PBS, backup host, migrazione live.

In esercizio la **3.21.0** (8 settembre): notifiche rifatte, riprova
automatica dopo un'ora, backup configurazione pianificato su tutti e quattro
i nodi.

**Trappola corrente**: il repo ha **tre worktree**, e l'8 settembre ci si è
messi a lavorare per sbaglio su un ramo 35 commit indietro rispetto a `main`.
Prima di toccare il codice: `git log --oneline -1` e `version.json`.
