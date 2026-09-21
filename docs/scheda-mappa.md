---
badge: Vivo
tono: ok
famiglia: 01-nucleo
ordine: 100
stato: manutenzione
prossimo: domattina leggere le corse delle 02:00 di dts-repl e /api/health (battito); poi Domarc alla 3.24.0
---
cruscotto backup/replica Proxmox (ZFS Sanoid/Syncoid, PBS)

Otto tipologie di attività sotto un solo cruscotto: replica VM, snapshot,
replica dati, sync NAS, backup e recovery PBS, backup host, migrazione live.

**DTS alla 3.24.0 dal 22 settembre** (Domarc ancora 3.21.3): scheduler con
battito e tetto per check (`docs/vita-dello-scheduler.md`), il job segue la
VM nel cluster (`docs/il-job-segue-la-vm.md`), replica senza l'uuid della
sorgente e «Attiva DR» (`docs/identita-replica.md`).

**Trappola corrente**: il repo ha **tre worktree** (l'8 settembre si è
lavorato su un ramo 35 commit indietro). Prima di toccare il codice:
`git branch --show-current` e `version.json`.
